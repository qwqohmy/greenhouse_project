from __future__ import annotations

import argparse
import csv
import json
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
        description="Evaluate CLIP-MVP adaptations with strict leave-one-group-out validation."
    )
    parser.add_argument("--features", type=Path)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def make_model(training_count: int) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("pca", PCA(n_components=min(5, training_count - 1), svd_solver="full")),
            ("ridge", RidgeCV(alphas=np.logspace(-3, 3, 13))),
        ]
    )


def cross_validated_predictions(
    features: np.ndarray, targets: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    predictions = np.zeros_like(targets, dtype=np.float64)
    baselines = np.zeros_like(targets, dtype=np.float64)
    for train_indices, test_indices in LeaveOneOut().split(features):
        for target_index in range(targets.shape[1]):
            target = targets[train_indices, target_index]
            mean = float(target.mean())
            std = float(target.std(ddof=0)) or 1.0
            model = make_model(len(train_indices))
            model.fit(features[train_indices], (target - mean) / std)
            predictions[test_indices[0], target_index] = (
                float(model.predict(features[test_indices])[0]) * std + mean
            )
            baselines[test_indices[0], target_index] = mean
    return predictions, baselines


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    method_root = Path(__file__).resolve().parents[1]
    plant_root = method_root.parent
    baseline_root = args.baseline_root or plant_root / "ResNet18-DepthAnything-Fusion"
    feature_path = args.features or method_root / "outputs" / "clip_features.npz"
    output_dir = args.output_dir or method_root / "outputs" / "comparison"
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_data = np.load(feature_path)
    targets = clip_data["y"]
    capture_ids = clip_data["capture_ids"].astype(str)
    target_names = clip_data["target_names"].astype(str)

    variants: dict[str, np.ndarray] = {
        "clip_full_mean": clip_data["X_clip_full_mean"],
        "clip_crop_mean": clip_data["X_clip_crop_mean"],
        "clip_full_stage_text": clip_data["X_clip_full_mean_stage_text"],
        "clip_crop_stage_text": clip_data["X_clip_crop_mean_stage_text"],
        "clip_full_four_camera": clip_data["X_clip_full_four_camera"],
        "clip_crop_four_camera": clip_data["X_clip_crop_four_camera"],
        "clip_crop_top": clip_data["X_clip_crop_top"],
        "clip_crop_side": clip_data["X_clip_crop_side"],
        "clip_crop_top_side": clip_data["X_clip_crop_top_side"],
        "clip_full_crop_fusion": np.concatenate(
            [clip_data["X_clip_full_top_side"], clip_data["X_clip_crop_top_side"]],
            axis=1,
        ),
    }
    notes = {
        "clip_full_mean": "Original CLIP-MVP-style mean of 24 full-frame view embeddings.",
        "clip_crop_mean": "Original CLIP-MVP-style mean of 24 cropped view embeddings.",
        "clip_full_stage_text": "Full-frame mean plus zero-shot CLIP growth-level prompt.",
        "clip_crop_stage_text": "Crop mean plus zero-shot CLIP growth-level prompt.",
        "clip_full_four_camera": "Four camera means plus global view standard deviation.",
        "clip_crop_four_camera": "Cropped four-camera means plus global view standard deviation.",
        "clip_crop_top": "Cropped top-view cameras only, preserving camera means and variation.",
        "clip_crop_side": "Cropped side-view cameras only, preserving camera means and variation.",
        "clip_crop_top_side": "Cropped top and side descriptors concatenated.",
        "clip_full_crop_fusion": "Full-frame and cropped top/side CLIP descriptors concatenated.",
    }

    branch_path = baseline_root / "outputs" / "features_branches.npz"
    full_rgb_path = baseline_root / "outputs" / "features_resnet18.npz"
    if branch_path.is_file():
        branches = np.load(branch_path)
        if not np.array_equal(branches["capture_ids"].astype(str), capture_ids):
            raise ValueError("CLIP and branch feature capture order differs")
        variants["clip_crop_depth_fusion"] = np.concatenate(
            [
                clip_data["X_clip_crop_top_side"],
                branches["X_depth_top"],
                branches["X_depth_side"],
            ],
            axis=1,
        )
        notes["clip_crop_depth_fusion"] = (
            "Cropped top/side CLIP descriptors plus existing top/side relative-depth features."
        )
        variants["resnet18_side_reference"] = branches["X_rgb_side"]
        notes["resnet18_side_reference"] = "Previous cropped side-RGB reference."

        if full_rgb_path.is_file():
            full_rgb = np.load(full_rgb_path)
            if not np.array_equal(full_rgb["capture_ids"].astype(str), capture_ids):
                raise ValueError("CLIP and full RGB feature capture order differs")
            variants["resnet18_current_best_reference"] = np.concatenate(
                [
                    full_rgb["X"],
                    branches["X_rgb_top"],
                    branches["X_rgb_side"],
                    branches["X_depth_top"],
                    branches["X_depth_side"],
                ],
                axis=1,
            )
            notes["resnet18_current_best_reference"] = (
                "Previous five-input ResNet18 RGB/depth fusion reference."
            )

    metric_rows: list[dict[str, object]] = []
    prediction_rows: list[dict[str, object]] = []
    baseline_mae: np.ndarray | None = None
    for variant_name, features in variants.items():
        predictions, baselines = cross_validated_predictions(features, targets)
        if baseline_mae is None:
            baseline_mae = np.asarray(
                [
                    mean_absolute_error(targets[:, index], baselines[:, index])
                    for index in range(targets.shape[1])
                ]
            )
        for target_index, target_name in enumerate(target_names):
            mae = float(
                mean_absolute_error(targets[:, target_index], predictions[:, target_index])
            )
            base = float(baseline_mae[target_index])
            metric_rows.append(
                {
                    "variant": variant_name,
                    "family": "reference" if variant_name.endswith("_reference") else "CLIP",
                    "target": target_name,
                    "mae": mae,
                    "baseline_mae": base,
                    "mae_ratio_vs_baseline": mae / base,
                    "r2": float(
                        r2_score(targets[:, target_index], predictions[:, target_index])
                    ),
                }
            )
        for sample_index, capture_id in enumerate(capture_ids):
            row: dict[str, object] = {
                "variant": variant_name,
                "capture_id": capture_id,
            }
            for target_index, target_name in enumerate(target_names):
                row[f"actual_{target_name}"] = float(targets[sample_index, target_index])
                row[f"predicted_{target_name}"] = float(
                    predictions[sample_index, target_index]
                )
            prediction_rows.append(row)

    summary_rows: list[dict[str, object]] = []
    for variant_name, features in variants.items():
        rows = [row for row in metric_rows if row["variant"] == variant_name]
        summary_rows.append(
            {
                "variant": variant_name,
                "family": "reference" if variant_name.endswith("_reference") else "CLIP",
                "feature_count": features.shape[1],
                "mean_mae_ratio_vs_baseline": float(
                    np.mean([float(row["mae_ratio_vs_baseline"]) for row in rows])
                ),
                "targets_better_than_baseline": sum(
                    float(row["mae_ratio_vs_baseline"]) < 1.0 for row in rows
                ),
                "mean_r2": float(np.mean([float(row["r2"]) for row in rows])),
                "notes": notes[variant_name],
            }
        )
    summary_rows.sort(key=lambda row: float(row["mean_mae_ratio_vs_baseline"]))

    best_all_rows: list[dict[str, object]] = []
    best_clip_rows: list[dict[str, object]] = []
    for target_name in target_names:
        candidates = [row for row in metric_rows if row["target"] == target_name]
        best_all_rows.append(min(candidates, key=lambda row: float(row["mae"])))
        clip_candidates = [row for row in candidates if row["family"] == "CLIP"]
        best_clip_rows.append(min(clip_candidates, key=lambda row: float(row["mae"])))

    write_csv(output_dir / "metrics.csv", metric_rows)
    write_csv(output_dir / "predictions.csv", prediction_rows)
    write_csv(output_dir / "summary.csv", summary_rows)
    write_csv(output_dir / "best_variant_per_target.csv", best_all_rows)
    write_csv(output_dir / "best_clip_variant_per_target.csv", best_clip_rows)

    result = {
        "sample_count": len(capture_ids),
        "validation": "LeaveOneOut by capture group",
        "best_overall": summary_rows[0],
        "best_clip": next(row for row in summary_rows if row["family"] == "CLIP"),
        "reference": next(
            (
                row
                for row in summary_rows
                if row["variant"] == "resnet18_current_best_reference"
            ),
            None,
        ),
    }
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("variant                              MAE/base  better  mean_R2  dims")
    for row in summary_rows:
        print(
            f"{str(row['variant']):<36} "
            f"{float(row['mean_mae_ratio_vs_baseline']):>8.4f}  "
            f"{int(row['targets_better_than_baseline']):>2}/7  "
            f"{float(row['mean_r2']):>7.4f}  "
            f"{int(row['feature_count']):>5}"
        )
    print(f"Summary: {output_dir / 'summary.csv'}")
    print(f"Result: {output_dir / 'result.json'}")


if __name__ == "__main__":
    main()
