from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare paper-style XGBoost, Random Forest, and linear regressors."
    )
    parser.add_argument("--features", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def xgboost_model() -> XGBRegressor:
    return XGBRegressor(
        objective="reg:squarederror",
        n_estimators=100,
        max_depth=2,
        learning_rate=0.05,
        min_child_weight=2,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=10.0,
        tree_method="hist",
        n_jobs=1,
        random_state=42,
        verbosity=0,
    )


def make_model(name: str, feature_count: int, training_count: int):
    pca_components = min(3, feature_count, training_count - 1)
    if name == "linear_pca3":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("pca", PCA(n_components=pca_components, svd_solver="full")),
                ("model", LinearRegression()),
            ]
        )
    if name == "random_forest":
        return RandomForestRegressor(
            n_estimators=200,
            max_depth=3,
            min_samples_leaf=2,
            max_features=0.8,
            n_jobs=-1,
            random_state=42,
        )
    if name == "xgboost":
        return xgboost_model()
    if name == "xgboost_pca3":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("pca", PCA(n_components=pca_components, svd_solver="full")),
                ("model", xgboost_model()),
            ]
        )
    raise ValueError(name)


def cross_validated_predictions(
    features: np.ndarray, targets: np.ndarray, model_name: str
) -> tuple[np.ndarray, np.ndarray]:
    predictions = np.zeros_like(targets, dtype=np.float64)
    baselines = np.zeros_like(targets, dtype=np.float64)
    for train_indices, test_indices in LeaveOneOut().split(features):
        for target_index in range(targets.shape[1]):
            target = targets[train_indices, target_index]
            mean = float(target.mean())
            std = float(target.std(ddof=0)) or 1.0
            model = make_model(model_name, features.shape[1], len(train_indices))
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
    feature_path = args.features or method_root / "outputs" / "handcrafted_features.npz"
    output_dir = args.output_dir or method_root / "outputs" / "comparison"
    output_dir.mkdir(parents=True, exist_ok=True)

    data = np.load(feature_path)
    targets = data["y"]
    capture_ids = data["capture_ids"].astype(str)
    target_names = data["target_names"].astype(str)
    feature_sets = {
        "paper_all_mean": data["X_paper_all_mean"],
        "paper_top_mean": data["X_paper_top_mean"],
        "paper_top_stats": data["X_paper_top_stats"],
        "paper_side_stats": data["X_paper_side_stats"],
        "paper_top_side_stats": data["X_paper_top_side_stats"],
        "paper_four_camera": data["X_paper_four_camera"],
        "rgb_shape_top_side_stats": data["X_rgb_shape_top_side_stats"],
        "rgb_shape_depth_top_side_stats": data[
            "X_rgb_shape_depth_top_side_stats"
        ],
        "rgb_shape_depth_four_camera": data["X_rgb_shape_depth_four_camera"],
    }
    model_names = ["xgboost", "xgboost_pca3", "random_forest", "linear_pca3"]

    metric_rows: list[dict[str, object]] = []
    prediction_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    baseline_mae: np.ndarray | None = None

    for feature_name, features in feature_sets.items():
        for model_name in model_names:
            variant = f"{model_name}__{feature_name}"
            predictions, baselines = cross_validated_predictions(
                features, targets, model_name
            )
            if baseline_mae is None:
                baseline_mae = np.asarray(
                    [
                        mean_absolute_error(targets[:, index], baselines[:, index])
                        for index in range(targets.shape[1])
                    ]
                )
            variant_metrics: list[dict[str, object]] = []
            for target_index, target_name in enumerate(target_names):
                mae = float(
                    mean_absolute_error(
                        targets[:, target_index], predictions[:, target_index]
                    )
                )
                base = float(baseline_mae[target_index])
                row = {
                    "variant": variant,
                    "model": model_name,
                    "feature_set": feature_name,
                    "target": target_name,
                    "mae": mae,
                    "baseline_mae": base,
                    "mae_ratio_vs_baseline": mae / base,
                    "r2": float(
                        r2_score(targets[:, target_index], predictions[:, target_index])
                    ),
                }
                metric_rows.append(row)
                variant_metrics.append(row)

            summary_rows.append(
                {
                    "variant": variant,
                    "model": model_name,
                    "feature_set": feature_name,
                    "feature_count": features.shape[1],
                    "mean_mae_ratio_vs_baseline": float(
                        np.mean(
                            [float(row["mae_ratio_vs_baseline"]) for row in variant_metrics]
                        )
                    ),
                    "targets_better_than_baseline": sum(
                        float(row["mae_ratio_vs_baseline"]) < 1.0
                        for row in variant_metrics
                    ),
                    "mean_r2": float(
                        np.mean([float(row["r2"]) for row in variant_metrics])
                    ),
                }
            )

            for sample_index, capture_id in enumerate(capture_ids):
                row: dict[str, object] = {"variant": variant, "capture_id": capture_id}
                for target_index, target_name in enumerate(target_names):
                    row[f"actual_{target_name}"] = float(
                        targets[sample_index, target_index]
                    )
                    row[f"predicted_{target_name}"] = float(
                        predictions[sample_index, target_index]
                    )
                prediction_rows.append(row)
            print(f"Evaluated {variant}")

    summary_rows.sort(key=lambda row: float(row["mean_mae_ratio_vs_baseline"]))
    best_xgb_rows: list[dict[str, object]] = []
    for target_name in target_names:
        candidates = [
            row
            for row in metric_rows
            if row["target"] == target_name and str(row["model"]).startswith("xgboost")
        ]
        best_xgb_rows.append(min(candidates, key=lambda row: float(row["mae"])))

    write_csv(output_dir / "metrics.csv", metric_rows)
    write_csv(output_dir / "predictions.csv", prediction_rows)
    write_csv(output_dir / "summary.csv", summary_rows)
    write_csv(output_dir / "best_xgboost_per_target.csv", best_xgb_rows)

    best_by_family = {}
    for model_name in model_names:
        best_by_family[model_name] = next(
            row for row in summary_rows if row["model"] == model_name
        )
    result = {
        "sample_count": len(capture_ids),
        "validation": "LeaveOneOut by capture group",
        "fixed_hyperparameters": True,
        "best_overall": summary_rows[0],
        "best_by_model": best_by_family,
    }
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\nvariant                                                    MAE/base better mean_R2 dims")
    for row in summary_rows[:15]:
        print(
            f"{str(row['variant']):<58} "
            f"{float(row['mean_mae_ratio_vs_baseline']):>8.4f} "
            f"{int(row['targets_better_than_baseline']):>2}/7 "
            f"{float(row['mean_r2']):>7.4f} "
            f"{int(row['feature_count']):>4}"
        )
    print(f"Summary: {output_dir / 'summary.csv'}")
    print(f"Result: {output_dir / 'result.json'}")


if __name__ == "__main__":
    main()
