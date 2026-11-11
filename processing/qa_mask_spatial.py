import os
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(os.environ.get('SAM_ROOT','data/multispectral_sam'))
FRAME_W = 2448
FRAME_H = 2048


def main() -> None:
    rows = []
    for success_path in sorted(ROOT.rglob("_SUCCESS.json")):
        meta = json.loads(success_path.read_text(encoding="utf-8"))
        prompts = {int(x["plant_number"]): x for x in meta["prompts"]}
        for plant in meta["plants"]:
            number = int(plant["plant_number"])
            prompt = prompts[number]
            expected = prompt.get("expected_center_xy")
            if not expected:
                continue
            mask_path = success_path.parent / f"plant-{number:02d}" / "mask.png"
            with Image.open(mask_path) as image:
                mask = np.asarray(image.convert("L")) > 0
            area = int(mask.sum())
            if not area:
                continue
            box = [int(v) for v in plant["crop_box_xyxy"]]
            ys, xs = np.nonzero(mask)
            gx = xs + box[0]
            gy = ys + box[1]
            ex = float(expected[0]) * FRAME_W
            ey = float(expected[1]) * FRAME_H
            d = np.sqrt(((gx - ex) / FRAME_W) ** 2 + ((gy - ey) / FRAME_H) ** 2)
            frame_edge = (gx < 80) | (gx >= FRAME_W - 80) | (gy < 80) | (gy >= FRAME_H - 80)

            nlabels, labels, stats, centroids = cv2.connectedComponentsWithStats(
                mask.astype(np.uint8), 8
            )
            if nlabels > 1:
                largest_idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                largest_area = int(stats[largest_idx, cv2.CC_STAT_AREA])
                largest_cx = float(centroids[largest_idx, 0] + box[0])
                largest_cy = float(centroids[largest_idx, 1] + box[1])
                largest_center_distance = float(
                    np.sqrt(
                        ((largest_cx - ex) / FRAME_W) ** 2
                        + ((largest_cy - ey) / FRAME_H) ** 2
                    )
                )
            else:
                largest_area = 0
                largest_center_distance = 0.0

            rows.append(
                {
                    "source_folder": meta["source_folder"],
                    "captured_at": meta["captured_at"],
                    "light_condition": meta["light_condition"],
                    "source_channel": meta["source_channel_for_segmentation"],
                    "layout": meta["layout_code"],
                    "plant_number": number,
                    "quality": plant["quality"],
                    "mask_source": prompt.get("mask_source", "unknown"),
                    "area": area,
                    "far15_fraction": round(float((d > 0.15).mean()), 6),
                    "far20_fraction": round(float((d > 0.20).mean()), 6),
                    "far25_fraction": round(float((d > 0.25).mean()), 6),
                    "frame_edge_fraction": round(float(frame_edge.mean()), 6),
                    "mask_centroid_distance": round(
                        float(
                            np.sqrt(
                                (((gx.mean() - ex) / FRAME_W) ** 2)
                                + (((gy.mean() - ey) / FRAME_H) ** 2)
                            )
                        ),
                        6,
                    ),
                    "largest_component_area_ratio": round(largest_area / area, 6),
                    "largest_component_center_distance": round(
                        largest_center_distance, 6
                    ),
                }
            )

    result = {
        "top_far20": sorted(rows, key=lambda x: x["far20_fraction"], reverse=True)[:200],
        "top_frame_edge": sorted(
            rows, key=lambda x: x["frame_edge_fraction"], reverse=True
        )[:200],
        "top_centroid_distance": sorted(
            rows, key=lambda x: x["mask_centroid_distance"], reverse=True
        )[:200],
        "top_largest_component_distance": sorted(
            rows,
            key=lambda x: x["largest_component_center_distance"],
            reverse=True,
        )[:200],
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
