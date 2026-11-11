from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate frozen DINOv2 pooling and a compact learned view selector."
    )
    parser.add_argument("--features", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--epochs", type=int, default=800)
    parser.add_argument("--seeds", type=int, default=5)
    return parser.parse_args()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ridge_model(training_count: int) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("pca", PCA(n_components=min(5, training_count - 1), svd_solver="full")),
            ("ridge", RidgeCV(alphas=np.logspace(-3, 3, 13))),
        ]
    )


def farthest_views(views: np.ndarray, count: int) -> np.ndarray:
    """Select diverse views without labels, starting nearest to the sample mean."""
    center = views.mean(axis=0)
    selected = [int(np.argmax(views @ center))]
    distances = 1.0 - views @ views[selected[0]]
    while len(selected) < count:
        index = int(np.argmax(distances))
        selected.append(index)
        distances = np.minimum(distances, 1.0 - views @ views[index])
    return views[np.asarray(selected)]


def fixed_variants(
    views: np.ndarray, camera_ids: np.ndarray, role_ids: np.ndarray
) -> dict[str, np.ndarray]:
    result = {
        "dino_all_mean": views.mean(axis=1),
        "dino_all_mean_std": np.concatenate(
            [views.mean(axis=1), views.std(axis=1, ddof=0)], axis=1
        ),
        "dino_four_camera": np.concatenate(
            [
                *[views[:, camera_ids == camera].mean(axis=1) for camera in range(4)],
                views.std(axis=1, ddof=0),
            ],
            axis=1,
        ),
        "dino_top_side": np.concatenate(
            [
                views[:, role_ids == 0].mean(axis=1),
                views[:, role_ids == 1].mean(axis=1),
                views[:, role_ids == 0].std(axis=1, ddof=0),
                views[:, role_ids == 1].std(axis=1, ddof=0),
            ],
            axis=1,
        ),
    }
    for count in (4, 8, 12):
        selected = np.stack([farthest_views(sample, count) for sample in views])
        result[f"dino_diverse_{count}"] = np.concatenate(
            [selected.mean(axis=1), selected.std(axis=1, ddof=0)], axis=1
        )
    return result


def ridge_predictions(features: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    predictions = np.zeros_like(targets, dtype=np.float64)
    baselines = np.zeros_like(targets, dtype=np.float64)
    for train_indices, test_indices in LeaveOneOut().split(features):
        for target_index in range(targets.shape[1]):
            target = targets[train_indices, target_index]
            mean = float(target.mean())
            std = float(target.std(ddof=0)) or 1.0
            model = ridge_model(len(train_indices))
            model.fit(features[train_indices], (target - mean) / std)
            predictions[test_indices[0], target_index] = (
                float(model.predict(features[test_indices])[0]) * std + mean
            )
            baselines[test_indices[0], target_index] = mean
    return predictions, baselines


def learned_selector_predictions(
    views: np.ndarray,
    targets: np.ndarray,
    camera_ids: np.ndarray,
    role_ids: np.ndarray,
    angle_ids: np.ndarray,
    epochs: int,
    seed_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import torch
    from torch import nn

    class ViewSelector(nn.Module):
        def __init__(self, feature_count: int) -> None:
            super().__init__()
            self.camera = nn.Embedding(4, 3)
            self.role = nn.Embedding(2, 2)
            self.angle = nn.Embedding(6, 3)
            self.score = nn.Sequential(
                nn.Linear(feature_count + 8, 12),
                nn.Tanh(),
                nn.Linear(12, 1),
            )
            self.head = nn.Linear(feature_count * 3, targets.shape[1])

        def forward(
            self,
            x: torch.Tensor,
            camera: torch.Tensor,
            role: torch.Tensor,
            angle: torch.Tensor,
            mask: torch.Tensor | None = None,
        ) -> tuple[torch.Tensor, torch.Tensor]:
            metadata = torch.cat(
                [self.camera(camera), self.role(role), self.angle(angle)], dim=-1
            )
            metadata = metadata.unsqueeze(0).expand(x.shape[0], -1, -1)
            scores = self.score(torch.cat([x, metadata], dim=-1)).squeeze(-1)
            if mask is not None:
                scores = scores.masked_fill(~mask, -1e4)
            weights = torch.softmax(scores, dim=1)
            selected = (weights.unsqueeze(-1) * x).sum(dim=1)
            top = x[:, role == 0].mean(dim=1)
            side = x[:, role == 1].mean(dim=1)
            return self.head(torch.cat([selected, top, side], dim=-1)), weights

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    predictions = np.zeros_like(targets, dtype=np.float64)
    baselines = np.zeros_like(targets, dtype=np.float64)
    fold_weights = np.zeros((len(targets), views.shape[1]), dtype=np.float64)
    camera_tensor = torch.as_tensor(camera_ids, dtype=torch.long, device=device)
    role_tensor = torch.as_tensor(role_ids, dtype=torch.long, device=device)
    angle_tensor = torch.as_tensor(angle_ids, dtype=torch.long, device=device)

    for fold, (train_indices, test_indices) in enumerate(LeaveOneOut().split(views)):
        train_flat = views[train_indices].reshape(-1, views.shape[-1])
        component_count = min(12, len(train_indices) - 1, train_flat.shape[1])
        pca = PCA(n_components=component_count, whiten=True, random_state=0)
        pca.fit(train_flat)
        train_x = pca.transform(train_flat).reshape(len(train_indices), 24, -1)
        test_x = pca.transform(views[test_indices].reshape(-1, views.shape[-1])).reshape(
            1, 24, -1
        )
        target_mean = targets[train_indices].mean(axis=0)
        target_std = targets[train_indices].std(axis=0, ddof=0)
        target_std[target_std == 0] = 1.0
        train_y = (targets[train_indices] - target_mean) / target_std
        baselines[test_indices[0]] = target_mean

        seed_predictions = []
        seed_weights = []
        for seed in range(seed_count):
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            model = ViewSelector(component_count).to(device)
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.05)
            x_tensor = torch.as_tensor(train_x, dtype=torch.float32, device=device)
            y_tensor = torch.as_tensor(train_y, dtype=torch.float32, device=device)
            test_tensor = torch.as_tensor(test_x, dtype=torch.float32, device=device)
            model.train()
            for epoch in range(epochs):
                generator = torch.Generator(device=device).manual_seed(seed * epochs + epoch)
                keep = torch.rand(
                    (len(train_indices), 24), generator=generator, device=device
                ) > 0.20
                keep[:, 0] = True
                noise = torch.randn(
                    x_tensor.shape, generator=generator, device=device
                ) * 0.015
                output, _ = model(
                    x_tensor + noise,
                    camera_tensor,
                    role_tensor,
                    angle_tensor,
                    keep,
                )
                loss = nn.functional.smooth_l1_loss(output, y_tensor)
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            model.eval()
            with torch.inference_mode():
                output, weights = model(
                    test_tensor, camera_tensor, role_tensor, angle_tensor
                )
            seed_predictions.append(output.cpu().numpy()[0] * target_std + target_mean)
            seed_weights.append(weights.cpu().numpy()[0])
        predictions[test_indices[0]] = np.mean(seed_predictions, axis=0)
        fold_weights[test_indices[0]] = np.mean(seed_weights, axis=0)
        print(f"Learned selector fold {fold + 1}/{len(targets)} complete")
    return predictions, baselines, fold_weights


def main() -> None:
    args = parse_args()
    method_root = Path(__file__).resolve().parents[1]
    feature_path = args.features or method_root / "outputs" / "dinov2_view_features.npz"
    output_dir = args.output_dir or method_root / "outputs" / "comparison"
    output_dir.mkdir(parents=True, exist_ok=True)
    data = np.load(feature_path)
    views = data["X_views"].astype(np.float64)
    targets = data["y"].astype(np.float64)
    capture_ids = data["capture_ids"].astype(str)
    target_names = data["target_names"].astype(str)
    camera_ids = data["camera_ids"].astype(np.int64)
    role_ids = data["role_ids"].astype(np.int64)
    angle_ids = data["angle_ids"].astype(np.int64)

    variants: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, features in fixed_variants(views, camera_ids, role_ids).items():
        variants[name] = ridge_predictions(features, targets)

    selector_predictions, selector_baselines, selector_weights = learned_selector_predictions(
        views,
        targets,
        camera_ids,
        role_ids,
        angle_ids,
        args.epochs,
        args.seeds,
    )
    variants["dino_learned_view_selector"] = (
        selector_predictions,
        selector_baselines,
    )
    np.savez_compressed(
        output_dir / "learned_view_weights.npz",
        weights=selector_weights,
        capture_ids=capture_ids,
        camera_ids=camera_ids,
        role_ids=role_ids,
        angle_ids=angle_ids,
    )

    metric_rows: list[dict[str, object]] = []
    prediction_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for variant_name, (predictions, baselines) in variants.items():
        ratios = []
        r2_values = []
        better = 0
        for target_index, target_name in enumerate(target_names):
            mae = float(mean_absolute_error(targets[:, target_index], predictions[:, target_index]))
            baseline_mae = float(
                mean_absolute_error(targets[:, target_index], baselines[:, target_index])
            )
            ratio = mae / baseline_mae
            r2 = float(r2_score(targets[:, target_index], predictions[:, target_index]))
            ratios.append(ratio)
            r2_values.append(r2)
            better += ratio < 1.0
            metric_rows.append(
                {
                    "variant": variant_name,
                    "target": target_name,
                    "mae": mae,
                    "baseline_mae": baseline_mae,
                    "mae_ratio_vs_baseline": ratio,
                    "r2": r2,
                }
            )
        summary_rows.append(
            {
                "variant": variant_name,
                "mean_mae_ratio_vs_baseline": float(np.mean(ratios)),
                "targets_better_than_baseline": better,
                "mean_r2": float(np.mean(r2_values)),
            }
        )
        for sample_index, capture_id in enumerate(capture_ids):
            row: dict[str, object] = {"variant": variant_name, "capture_id": capture_id}
            for target_index, target_name in enumerate(target_names):
                row[f"actual_{target_name}"] = float(targets[sample_index, target_index])
                row[f"predicted_{target_name}"] = float(predictions[sample_index, target_index])
            prediction_rows.append(row)

    summary_rows.sort(key=lambda row: float(row["mean_mae_ratio_vs_baseline"]))
    write_csv(output_dir / "metrics.csv", metric_rows)
    write_csv(output_dir / "predictions.csv", prediction_rows)
    write_csv(output_dir / "summary.csv", summary_rows)
    result = {
        "sample_count": len(capture_ids),
        "views_per_sample": views.shape[1],
        "validation": "LeaveOneOut by capture group; PCA fitted inside each fold",
        "seeds_for_learned_selector": args.seeds,
        "epochs_per_fold": args.epochs,
        "best": summary_rows[0],
    }
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("variant                         MAE/base  better  mean_R2")
    for row in summary_rows:
        print(
            f"{str(row['variant']):<31} "
            f"{float(row['mean_mae_ratio_vs_baseline']):>8.4f}  "
            f"{int(row['targets_better_than_baseline']):>2}/7  "
            f"{float(row['mean_r2']):>7.4f}"
        )
    print(f"Result: {output_dir / 'result.json'}")


if __name__ == "__main__":
    main()
