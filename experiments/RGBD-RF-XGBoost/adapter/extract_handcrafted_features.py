from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PAPER_FEATURES = [
    "leaf_pixel_ratio",
    "edge_pixel_ratio",
    "exg",
    "exr",
    "vari",
]

SHAPE_FEATURES = [
    "bbox_width_ratio",
    "bbox_height_ratio",
    "hull_area_ratio",
    "solidity",
    "equivalent_diameter_ratio",
    "eccentricity",
    "perimeter_ratio",
]

DEPTH_FEATURES = [
    "depth_mean",
    "depth_std",
    "depth_p10",
    "depth_median",
    "depth_p90",
    "depth_range_10_90",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract interpretable RGB, shape, and relative-depth features."
    )
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def generated_path(path_text: str, baseline_root: Path) -> Path:
    raw = Path(path_text)
    parts = list(raw.parts)
    lowered = [part.lower() for part in parts]
    if "outputs" in lowered:
        output_index = lowered.index("outputs")
        relocated = baseline_root.joinpath(*parts[output_index:])
        if relocated.is_file():
            return relocated
    if raw.is_file():
        return raw
    raise FileNotFoundError(path_text)


def vegetation_mask(image: np.ndarray) -> np.ndarray:
    blue, green, red = cv2.split(image.astype(np.float32))
    total = red + green + blue
    valid = total > 30.0
    total_safe = np.maximum(total, 1.0)
    red_n = red / total_safe
    green_n = green / total_safe
    blue_n = blue / total_safe
    exg = 2.0 * green_n - red_n - blue_n

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    color_mask = (
        valid
        & (value > 35)
        & (hue >= 18)
        & (hue <= 100)
        & (green >= 0.90 * red)
        & (green >= 0.95 * blue)
        & (exg > 0.015)
    )

    mask = (color_mask.astype(np.uint8) * 255)
    kernel_size = max(3, int(round(min(image.shape[:2]) / 300.0)) | 1)
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if component_count <= 1:
        return mask.astype(bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max())
    minimum = max(25, int(round(largest * 0.02)))
    keep = np.zeros(component_count, dtype=bool)
    keep[1:] = areas >= minimum
    cleaned = keep[labels]
    return cleaned


def image_features(
    rgb_path: Path, depth_path: Path
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    image = cv2.imread(str(rgb_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read RGB image: {rgb_path}")
    mask = vegetation_mask(image)
    if int(mask.sum()) < 25:
        raise ValueError(f"Vegetation mask is empty: {rgb_path}")

    blue, green, red = cv2.split(image.astype(np.float32))
    total = np.maximum(red + green + blue, 1.0)
    red_n = red / total
    green_n = green / total
    blue_n = blue / total
    exg_image = 2.0 * green_n - red_n - blue_n
    exr_image = 1.4 * red_n - green_n
    vari_image = exg_image - exr_image

    masked_image = np.zeros_like(image)
    masked_image[mask] = image[mask]
    edges = cv2.Canny(masked_image, 70, 100)
    image_area = float(image.shape[0] * image.shape[1])

    mask_u8 = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    points = np.concatenate(contours, axis=0)
    hull = cv2.convexHull(points)
    hull_area = float(cv2.contourArea(hull))
    mask_area = float(mask.sum())
    x, y, width, height = cv2.boundingRect(points)
    perimeter = float(sum(cv2.arcLength(contour, True) for contour in contours))
    equivalent_diameter = float(np.sqrt(4.0 * mask_area / np.pi))
    eccentricity = 0.0
    if len(points) >= 5:
        _, axes, _ = cv2.fitEllipse(points)
        major = max(float(axes[0]), float(axes[1]))
        minor = min(float(axes[0]), float(axes[1]))
        if major > 0:
            eccentricity = float(np.sqrt(max(0.0, 1.0 - (minor / major) ** 2)))

    depth = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
    if depth is None:
        raise ValueError(f"Could not read depth image: {depth_path}")
    if depth.shape[:2] != mask.shape:
        depth = cv2.resize(
            depth, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST
        )
    depth_values = depth.astype(np.float32)[mask]
    depth_scale = 65535.0 if float(depth_values.max()) > 255.0 else 255.0
    depth_values = depth_values / depth_scale
    depth_p10, depth_median, depth_p90 = np.percentile(depth_values, [10, 50, 90])

    values = {
        "leaf_pixel_ratio": mask_area / image_area,
        "edge_pixel_ratio": float(np.count_nonzero(edges)) / image_area,
        "exg": float(exg_image[mask].mean()),
        "exr": float(exr_image[mask].mean()),
        "vari": float(vari_image[mask].mean()),
        "bbox_width_ratio": float(width) / image.shape[1],
        "bbox_height_ratio": float(height) / image.shape[0],
        "hull_area_ratio": hull_area / image_area,
        "solidity": mask_area / max(hull_area, 1.0),
        "equivalent_diameter_ratio": equivalent_diameter / np.sqrt(image_area),
        "eccentricity": eccentricity,
        "perimeter_ratio": perimeter / (2.0 * (image.shape[0] + image.shape[1])),
        "depth_mean": float(depth_values.mean()),
        "depth_std": float(depth_values.std(ddof=0)),
        "depth_p10": float(depth_p10),
        "depth_median": float(depth_median),
        "depth_p90": float(depth_p90),
        "depth_range_10_90": float(depth_p90 - depth_p10),
    }
    ordered_names = PAPER_FEATURES + SHAPE_FEATURES + DEPTH_FEATURES
    return np.asarray([values[name] for name in ordered_names], dtype=np.float32), mask, values


def mean_std(values: np.ndarray) -> np.ndarray:
    return np.concatenate([values.mean(axis=0), values.std(axis=0, ddof=0)]).astype(
        np.float32
    )


def make_preview(image: np.ndarray, mask: np.ndarray, label: str) -> np.ndarray:
    overlay = image.copy()
    green = np.zeros_like(image)
    green[:, :, 1] = 220
    overlay[mask] = cv2.addWeighted(image, 0.55, green, 0.45, 0)[mask]
    canvas = np.zeros((300, 360, 3), dtype=np.uint8)
    available_height = 260
    scale = min(360 / overlay.shape[1], available_height / overlay.shape[0])
    resized = cv2.resize(
        overlay,
        (max(1, int(overlay.shape[1] * scale)), max(1, int(overlay.shape[0] * scale))),
        interpolation=cv2.INTER_AREA,
    )
    x = (360 - resized.shape[1]) // 2
    y = 35 + (available_height - resized.shape[0]) // 2
    canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    cv2.putText(
        canvas,
        label,
        (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


def main() -> None:
    args = parse_args()
    method_root = Path(__file__).resolve().parents[1]
    plant_root = method_root.parent
    baseline_root = args.baseline_root or plant_root / "ResNet18-DepthAnything-Fusion"
    output_path = args.output or method_root / "outputs" / "handcrafted_features.npz"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = load_json(baseline_root / "outputs" / "manifest.json")
    depth_index = load_json(
        baseline_root / "outputs" / "depth_dataset" / "index.json"
    )
    entry_lookup = {entry["source_path"].lower(): entry for entry in depth_index["entries"]}
    role_cameras = {
        role: [str(camera) for camera in cameras]
        for role, cameras in manifest.get(
            "camera_roles", {"top": [1, 2], "side": [3, 4]}
        ).items()
    }

    feature_rows: dict[str, list[np.ndarray]] = {}
    diagnostic_rows: list[dict[str, object]] = []
    labels: list[list[float]] = []
    capture_ids: list[str] = []
    previews: list[np.ndarray] = []
    all_feature_names = PAPER_FEATURES + SHAPE_FEATURES + DEPTH_FEATURES
    invalid_view_count = 0

    for group_index, group in enumerate(manifest["groups"], start=1):
        by_camera: dict[str, np.ndarray] = {}
        for camera in range(1, 5):
            camera_key = str(camera)
            rows: list[np.ndarray] = []
            for view_index, source_path in enumerate(
                group["selected_images"][camera_key], start=1
            ):
                entry = entry_lookup[source_path.lower()]
                rgb_path = generated_path(entry["crop_path"], baseline_root)
                depth_path = generated_path(entry["depth_path"], baseline_root)
                try:
                    row, mask, values = image_features(rgb_path, depth_path)
                except ValueError as error:
                    if "Vegetation mask is empty" not in str(error):
                        raise
                    invalid_view_count += 1
                    diagnostic_rows.append(
                        {
                            "capture_id": group["capture_id"],
                            "camera": camera,
                            "role": entry["role"],
                            "view_index": view_index,
                            "rgb_path": str(rgb_path),
                            "valid_view": False,
                            "invalid_reason": "no vegetation after RGB/depth crop",
                            **{name: "" for name in all_feature_names},
                        }
                    )
                    print(
                        f"  skip {group['capture_id']} CAM{camera} view {view_index}: "
                        "no vegetation"
                    )
                    continue
                rows.append(row)
                diagnostic_rows.append(
                    {
                        "capture_id": group["capture_id"],
                        "camera": camera,
                        "role": entry["role"],
                        "view_index": view_index,
                        "rgb_path": str(rgb_path),
                        "valid_view": True,
                        "invalid_reason": "",
                        **values,
                    }
                )
                if camera == 2 and view_index == 1:
                    image = cv2.imread(str(rgb_path), cv2.IMREAD_COLOR)
                    previews.append(make_preview(image, mask, group["capture_id"]))
            by_camera[camera_key] = (
                np.stack(rows)
                if rows
                else np.empty((0, len(all_feature_names)), dtype=np.float32)
            )

        all_views = np.concatenate(
            [by_camera[str(camera)] for camera in range(1, 5) if len(by_camera[str(camera)])]
        )
        top_views = np.concatenate(
            [by_camera[camera] for camera in role_cameras["top"] if len(by_camera[camera])]
        )
        side_views = np.concatenate(
            [by_camera[camera] for camera in role_cameras["side"] if len(by_camera[camera])]
        )

        def camera_mean(camera: int, feature_slice: slice) -> np.ndarray:
            camera_key = str(camera)
            if len(by_camera[camera_key]):
                return by_camera[camera_key][:, feature_slice].mean(axis=0)
            role_views = (
                top_views if camera_key in role_cameras["top"] else side_views
            )
            return role_views[:, feature_slice].mean(axis=0)

        paper_slice = slice(0, len(PAPER_FEATURES))
        shape_end = len(PAPER_FEATURES) + len(SHAPE_FEATURES)
        rgb_shape_slice = slice(0, shape_end)
        feature_values = {
            "X_paper_all_mean": all_views[:, paper_slice].mean(axis=0),
            "X_paper_top_mean": top_views[:, paper_slice].mean(axis=0),
            "X_paper_top_stats": mean_std(top_views[:, paper_slice]),
            "X_paper_side_stats": mean_std(side_views[:, paper_slice]),
            "X_paper_top_side_stats": np.concatenate(
                [mean_std(top_views[:, paper_slice]), mean_std(side_views[:, paper_slice])]
            ),
            "X_paper_four_camera": np.concatenate(
                [
                    *(camera_mean(camera, paper_slice) for camera in range(1, 5)),
                    all_views[:, paper_slice].std(axis=0, ddof=0),
                ]
            ),
            "X_rgb_shape_top_side_stats": np.concatenate(
                [
                    mean_std(top_views[:, rgb_shape_slice]),
                    mean_std(side_views[:, rgb_shape_slice]),
                ]
            ),
            "X_rgb_shape_depth_top_side_stats": np.concatenate(
                [mean_std(top_views), mean_std(side_views)]
            ),
            "X_rgb_shape_depth_four_camera": np.concatenate(
                [
                    *(camera_mean(camera, slice(0, len(all_feature_names))) for camera in range(1, 5)),
                    all_views.std(axis=0, ddof=0),
                ]
            ),
        }
        for name, value in feature_values.items():
            feature_rows.setdefault(name, []).append(value.astype(np.float32))

        capture_ids.append(group["capture_id"])
        labels.append(
            [float(group["labels"][target]) for target in manifest["primary_targets"]]
        )
        print(f"[{group_index}/{len(manifest['groups'])}] {group['capture_id']}")

    arrays = {name: np.stack(rows) for name, rows in feature_rows.items()}
    np.savez_compressed(
        output_path,
        **arrays,
        y=np.asarray(labels, dtype=np.float64),
        capture_ids=np.asarray(capture_ids),
        target_names=np.asarray(manifest["primary_targets"]),
    )

    diagnostics_path = output_path.with_name("per_view_features.csv")
    with diagnostics_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(diagnostic_rows[0]))
        writer.writeheader()
        writer.writerows(diagnostic_rows)

    rows = [np.concatenate(previews[index : index + 3], axis=1) for index in range(0, 9, 3)]
    preview_path = output_path.with_name("mask_contact_sheet.jpg")
    cv2.imwrite(str(preview_path), np.concatenate(rows, axis=0))

    metadata = {
        "sample_count": len(capture_ids),
        "images_per_group": 24,
        "paper_features": PAPER_FEATURES,
        "shape_features": SHAPE_FEATURES,
        "relative_depth_features": DEPTH_FEATURES,
        "all_per_view_features": all_feature_names,
        "feature_shapes": {name: list(array.shape) for name, array in arrays.items()},
        "valid_view_count": len(diagnostic_rows) - invalid_view_count,
        "invalid_view_count": invalid_view_count,
        "mask_preview": str(preview_path),
    }
    output_path.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Features: {output_path}")
    print(f"Diagnostics: {diagnostics_path}")
    print(f"Mask preview: {preview_path}")
    for name, array in arrays.items():
        print(f"  {name}: {array.shape}")


if __name__ == "__main__":
    main()
