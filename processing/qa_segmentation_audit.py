import os
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(os.environ.get('SAM_ROOT','data/multispectral_sam'))


def iou(a: list[int], b: list[int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def issue(kind: str, metadata: dict, plant: dict, **details: object) -> dict:
    return {
        "kind": kind,
        "source_folder": metadata["source_folder"],
        "captured_at": metadata["captured_at"],
        "light_condition": metadata["light_condition"],
        "layout": metadata["layout_code"],
        "plant_number": int(plant["plant_number"]),
        **details,
    }


def main() -> None:
    counts: Counter[str] = Counter()
    issues: list[dict] = []
    metrics: list[dict] = []

    for success_path in sorted(ROOT.rglob("_SUCCESS.json")):
        counts["captures"] += 1
        metadata = json.loads(success_path.read_text(encoding="utf-8"))
        capture_dir = success_path.parent
        prompt_by_number = {
            int(prompt["plant_number"]): prompt for prompt in metadata.get("prompts", [])
        }
        crop_boxes: list[tuple[int, list[int]]] = []
        mask_hashes: dict[str, list[int]] = {}

        for plant in metadata["plants"]:
            counts["plants"] += 1
            number = int(plant["plant_number"])
            plant_dir = capture_dir / f"plant-{number:02d}"
            mask_path = plant_dir / "mask.png"
            source_path = plant_dir / (
                "Color.png"
                if (plant_dir / "Color.png").is_file()
                else "L540.png"
            )
            box = [int(v) for v in plant["crop_box_xyxy"]]
            crop_boxes.append((number, box))
            prompt = prompt_by_number.get(number, {})

            try:
                with Image.open(mask_path) as image:
                    mask_raw = np.asarray(image.convert("L"))
                with Image.open(source_path) as image:
                    source = np.asarray(image)
            except Exception as exc:
                issues.append(issue("unreadable_image", metadata, plant, error=repr(exc)))
                continue

            h, w = mask_raw.shape
            expected_w = box[2] - box[0]
            expected_h = box[3] - box[1]
            if (w, h) != (expected_w, expected_h):
                issues.append(
                    issue(
                        "crop_size_mismatch",
                        metadata,
                        plant,
                        actual=[w, h],
                        expected=[expected_w, expected_h],
                    )
                )
            if source.shape[:2] != (h, w):
                issues.append(
                    issue(
                        "source_mask_size_mismatch",
                        metadata,
                        plant,
                        source_shape=list(source.shape[:2]),
                        mask_shape=[h, w],
                    )
                )

            unique_values = np.unique(mask_raw)
            if not set(unique_values.tolist()).issubset({0, 255}):
                issues.append(
                    issue(
                        "non_binary_mask",
                        metadata,
                        plant,
                        values=unique_values[:20].tolist(),
                    )
                )

            mask = mask_raw > 0
            area = int(mask.sum())
            metadata_area = int(plant["mask_area_pixels"])
            if area != metadata_area:
                issues.append(
                    issue(
                        "mask_area_mismatch",
                        metadata,
                        plant,
                        actual=area,
                        metadata=metadata_area,
                    )
                )

            occupancy = area / (w * h) if w and h else 0.0
            border_pixels = 0
            if area:
                border_pixels = int(
                    mask[0, :].sum()
                    + mask[-1, :].sum()
                    + mask[:, 0].sum()
                    + mask[:, -1].sum()
                )
            if border_pixels:
                issues.append(
                    issue(
                        "mask_touches_crop_border",
                        metadata,
                        plant,
                        area=area,
                        border_pixels=border_pixels,
                        occupancy=round(occupancy, 6),
                    )
                )
            if occupancy > 0.82:
                issues.append(
                    issue(
                        "very_high_mask_occupancy",
                        metadata,
                        plant,
                        area=area,
                        occupancy=round(occupancy, 6),
                    )
                )

            binary = mask.astype(np.uint8)
            component_count = 0
            largest_ratio = 0.0
            significant_components = 0
            if area:
                nlabels, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
                component_areas = sorted(
                    (int(v) for v in stats[1:, cv2.CC_STAT_AREA]), reverse=True
                )
                component_count = len(component_areas)
                largest_ratio = component_areas[0] / area
                threshold = max(8, round(area * 0.01))
                significant_components = sum(v >= threshold for v in component_areas)
                if largest_ratio < 0.65 and significant_components >= 3:
                    issues.append(
                        issue(
                            "fragmented_mask",
                            metadata,
                            plant,
                            area=area,
                            component_count=component_count,
                            significant_components=significant_components,
                            largest_component_ratio=round(largest_ratio, 6),
                        )
                    )

            digest = hashlib.sha256(mask_raw.tobytes()).hexdigest()
            mask_hashes.setdefault(digest, []).append(number)

            expected_center = prompt.get("expected_center_xy")
            center_distance = None
            if expected_center:
                cx = ((box[0] + box[2]) / 2) / 2448.0
                cy = ((box[1] + box[3]) / 2) / 2048.0
                center_distance = math.dist((cx, cy), expected_center)
                if center_distance > 0.18:
                    issues.append(
                        issue(
                            "crop_far_from_expected_position",
                            metadata,
                            plant,
                            distance=round(center_distance, 6),
                            expected=[round(float(v), 6) for v in expected_center],
                            actual=[round(cx, 6), round(cy, 6)],
                        )
                    )

            if source.shape[:2] == (h, w):
                if source.ndim == 3:
                    outside_nonzero = int(np.any(source != 0, axis=2)[~mask].sum())
                    inside_nonzero = int(np.any(source != 0, axis=2)[mask].sum())
                else:
                    outside_nonzero = int((source[~mask] != 0).sum())
                    inside_nonzero = int((source[mask] != 0).sum())
                if outside_nonzero:
                    issues.append(
                        issue(
                            "nonzero_pixels_outside_mask",
                            metadata,
                            plant,
                            pixels=outside_nonzero,
                        )
                    )
                if area and inside_nonzero / area < 0.5:
                    issues.append(
                        issue(
                            "mostly_zero_inside_mask",
                            metadata,
                            plant,
                            area=area,
                            nonzero_inside=inside_nonzero,
                        )
                    )

            metrics.append(
                {
                    "source_folder": metadata["source_folder"],
                    "captured_at": metadata["captured_at"],
                    "light_condition": metadata["light_condition"],
                    "layout": metadata["layout_code"],
                    "plant_number": number,
                    "quality": plant["quality"],
                    "mask_source": prompt.get("mask_source", "unknown"),
                    "area": area,
                    "width": w,
                    "height": h,
                    "occupancy": round(occupancy, 6),
                    "border_pixels": border_pixels,
                    "component_count": component_count,
                    "significant_components": significant_components,
                    "largest_component_ratio": round(largest_ratio, 6),
                    "center_distance": None
                    if center_distance is None
                    else round(center_distance, 6),
                }
            )

        for digest, numbers in mask_hashes.items():
            if len(numbers) > 1:
                plants = [p for p in metadata["plants"] if int(p["plant_number"]) in numbers]
                if any(int(p["mask_area_pixels"]) > 0 for p in plants):
                    issues.append(
                        {
                            "kind": "duplicate_masks_within_capture",
                            "source_folder": metadata["source_folder"],
                            "captured_at": metadata["captured_at"],
                            "light_condition": metadata["light_condition"],
                            "layout": metadata["layout_code"],
                            "plant_numbers": numbers,
                        }
                    )

        for idx, (number_a, box_a) in enumerate(crop_boxes):
            for number_b, box_b in crop_boxes[idx + 1 :]:
                overlap = iou(box_a, box_b)
                if overlap > 0.72:
                    issues.append(
                        {
                            "kind": "strong_crop_overlap",
                            "source_folder": metadata["source_folder"],
                            "captured_at": metadata["captured_at"],
                            "light_condition": metadata["light_condition"],
                            "layout": metadata["layout_code"],
                            "plant_numbers": [number_a, number_b],
                            "iou": round(overlap, 6),
                        }
                    )

    kind_counts = Counter(item["kind"] for item in issues)
    ranked = sorted(
        metrics,
        key=lambda x: (
            x["quality"] == "ok",
            -x["border_pixels"],
            -x["occupancy"],
            x["largest_component_ratio"],
        ),
    )
    result = {
        "counts": dict(counts),
        "issue_counts": dict(sorted(kind_counts.items())),
        "issues": issues,
        "lowest_area": sorted(metrics, key=lambda x: x["area"])[:60],
        "highest_occupancy": sorted(metrics, key=lambda x: x["occupancy"], reverse=True)[:60],
        "most_border_contact": sorted(metrics, key=lambda x: x["border_pixels"], reverse=True)[:60],
        "most_fragmented": sorted(
            metrics,
            key=lambda x: (x["largest_component_ratio"], -x["significant_components"]),
        )[:60],
        "largest_center_distance": sorted(
            (x for x in metrics if x["center_distance"] is not None),
            key=lambda x: x["center_distance"],
            reverse=True,
        )[:60],
        "ranked_candidates": ranked[:100],
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
