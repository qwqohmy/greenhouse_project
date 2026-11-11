from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate fixed 50/50 CLIP-DINO ensembles.")
    parser.add_argument("--clip-predictions", type=Path, required=True)
    parser.add_argument("--dino-predictions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    clip_rows = read_rows(args.clip_predictions)
    dino_rows = read_rows(args.dino_predictions)
    clip_lookup = {(row["variant"], row["capture_id"]): row for row in clip_rows}
    dino_lookup = {(row["variant"], row["capture_id"]): row for row in dino_rows}
    capture_ids = sorted(
        {capture_id for variant, capture_id in clip_lookup if variant == "clip_full_mean"}
    )
    target_names = [
        key.removeprefix("actual_")
        for key in clip_lookup[("clip_full_mean", capture_ids[0])]
        if key.startswith("actual_")
    ]
    combinations = [
        ("clip_dino_all_mean_50_50", "dino_all_mean"),
        ("clip_dino_selector_50_50", "dino_learned_view_selector"),
        ("clip_dino_top_side_50_50", "dino_top_side"),
    ]
    metric_rows: list[dict[str, object]] = []
    prediction_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    actual = np.asarray(
        [
            [float(clip_lookup[("clip_full_mean", capture)][f"actual_{target}"]) for target in target_names]
            for capture in capture_ids
        ]
    )
    baseline = np.stack(
        [np.delete(actual, index, axis=0).mean(axis=0) for index in range(len(actual))]
    )
    baseline_mae = np.asarray(
        [mean_absolute_error(actual[:, index], baseline[:, index]) for index in range(len(target_names))]
    )

    for ensemble_name, dino_variant in combinations:
        clip_prediction = np.asarray(
            [
                [float(clip_lookup[("clip_full_mean", capture)][f"predicted_{target}"]) for target in target_names]
                for capture in capture_ids
            ]
        )
        dino_prediction = np.asarray(
            [
                [float(dino_lookup[(dino_variant, capture)][f"predicted_{target}"]) for target in target_names]
                for capture in capture_ids
            ]
        )
        prediction = 0.5 * clip_prediction + 0.5 * dino_prediction
        ratios = []
        r2_values = []
        for target_index, target_name in enumerate(target_names):
            mae = float(mean_absolute_error(actual[:, target_index], prediction[:, target_index]))
            ratio = mae / float(baseline_mae[target_index])
            r2 = float(r2_score(actual[:, target_index], prediction[:, target_index]))
            ratios.append(ratio)
            r2_values.append(r2)
            metric_rows.append(
                {
                    "variant": ensemble_name,
                    "target": target_name,
                    "mae": mae,
                    "baseline_mae": float(baseline_mae[target_index]),
                    "mae_ratio_vs_baseline": ratio,
                    "r2": r2,
                }
            )
        summary_rows.append(
            {
                "variant": ensemble_name,
                "mean_mae_ratio_vs_baseline": float(np.mean(ratios)),
                "targets_better_than_baseline": sum(value < 1.0 for value in ratios),
                "mean_r2": float(np.mean(r2_values)),
            }
        )
        for sample_index, capture_id in enumerate(capture_ids):
            row: dict[str, object] = {"variant": ensemble_name, "capture_id": capture_id}
            for target_index, target_name in enumerate(target_names):
                row[f"actual_{target_name}"] = float(actual[sample_index, target_index])
                row[f"predicted_{target_name}"] = float(prediction[sample_index, target_index])
            prediction_rows.append(row)

    summary_rows.sort(key=lambda row: float(row["mean_mae_ratio_vs_baseline"]))
    write_rows(args.output_dir / "summary.csv", summary_rows)
    write_rows(args.output_dir / "metrics.csv", metric_rows)
    write_rows(args.output_dir / "predictions.csv", prediction_rows)
    (args.output_dir / "result.json").write_text(
        json.dumps({"fixed_weight": 0.5, "best": summary_rows[0]}, indent=2),
        encoding="utf-8",
    )
    for row in summary_rows:
        print(
            f"{row['variant']}: {float(row['mean_mae_ratio_vs_baseline']):.4f}, "
            f"{row['targets_better_than_baseline']}/7, R2={float(row['mean_r2']):.4f}"
        )


if __name__ == "__main__":
    main()
