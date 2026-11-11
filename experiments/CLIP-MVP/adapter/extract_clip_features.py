from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract frozen CLIP embeddings for the nine clean multi-view groups."
    )
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="ViT-B/32")
    parser.add_argument("--batch-size", type=int, default=24)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def generated_path(path_text: str, baseline_root: Path) -> Path:
    """Relocate paths recorded before the baseline project was moved."""
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


def l2_normalize(array: "np.ndarray") -> "np.ndarray":
    import numpy as np

    norm = np.linalg.norm(array, axis=-1, keepdims=True)
    return array / np.maximum(norm, 1e-12)


def main() -> None:
    args = parse_args()
    method_root = Path(__file__).resolve().parents[1]
    plant_root = method_root.parent
    baseline_root = args.baseline_root or plant_root / "ResNet18-DepthAnything-Fusion"
    output_path = args.output or method_root / "outputs" / "clip_features.npz"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = baseline_root / "outputs" / "manifest.json"
    depth_index_path = baseline_root / "outputs" / "depth_dataset" / "index.json"
    manifest = load_json(manifest_path)
    depth_index = load_json(depth_index_path)
    entry_lookup = {entry["source_path"].lower(): entry for entry in depth_index["entries"]}

    os.environ.setdefault("TORCH_HOME", str(method_root / ".cache" / "torch"))
    os.environ.setdefault("PYTHONUTF8", "1")

    import clip
    import numpy as np
    import torch
    from PIL import Image

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    download_root = method_root / ".cache" / "clip"
    download_root.mkdir(parents=True, exist_ok=True)
    model, preprocess = clip.load(
        args.model,
        device=device,
        jit=False,
        download_root=str(download_root),
    )
    model.eval()
    print(f"Device: {device}")
    print(f"CLIP model: {args.model}")

    stage_prompts = [f"plant at approximately level {level}" for level in range(1, 6)]
    with torch.inference_mode():
        tokens = clip.tokenize(stage_prompts).to(device)
        text_embeddings = model.encode_text(tokens).float().cpu().numpy()
    text_embeddings = l2_normalize(text_embeddings).astype(np.float32)

    def encode(paths: list[Path]) -> np.ndarray:
        chunks: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(paths), args.batch_size):
                tensors = []
                for path in paths[start : start + args.batch_size]:
                    with Image.open(path) as image:
                        tensors.append(preprocess(image.convert("RGB")))
                batch = torch.stack(tensors).to(device, non_blocking=True)
                chunks.append(model.encode_image(batch).float().cpu().numpy())
        return np.concatenate(chunks, axis=0).astype(np.float32)

    role_cameras = {
        role: [str(camera) for camera in cameras]
        for role, cameras in manifest.get(
            "camera_roles", {"top": [1, 2], "side": [3, 4]}
        ).items()
    }
    if set(role_cameras) != {"top", "side"}:
        raise ValueError(f"Expected top/side camera roles, got {role_cameras}")

    def aggregate(
        camera_embeddings: dict[str, np.ndarray], modality: str
    ) -> dict[str, np.ndarray | int]:
        camera_order = [str(camera) for camera in range(1, 5)]
        all_views = np.concatenate([camera_embeddings[camera] for camera in camera_order])
        camera_means = [camera_embeddings[camera].mean(axis=0) for camera in camera_order]
        result: dict[str, np.ndarray | int] = {
            f"X_clip_{modality}_mean": all_views.mean(axis=0).astype(np.float32),
            f"X_clip_{modality}_four_camera": np.concatenate(
                [*camera_means, all_views.std(axis=0, ddof=0)]
            ).astype(np.float32),
        }

        role_vectors: list[np.ndarray] = []
        for role in ("top", "side"):
            cameras = role_cameras[role]
            role_views = np.concatenate([camera_embeddings[camera] for camera in cameras])
            role_vector = np.concatenate(
                [
                    *(camera_embeddings[camera].mean(axis=0) for camera in cameras),
                    role_views.std(axis=0, ddof=0),
                ]
            ).astype(np.float32)
            result[f"X_clip_{modality}_{role}"] = role_vector
            role_vectors.append(role_vector)
        result[f"X_clip_{modality}_top_side"] = np.concatenate(role_vectors).astype(
            np.float32
        )

        normalized_mean = l2_normalize(all_views.mean(axis=0, keepdims=True))[0]
        stage_index = int(np.argmax(text_embeddings @ normalized_mean))
        result[f"X_clip_{modality}_mean_stage_text"] = np.concatenate(
            [all_views.mean(axis=0), text_embeddings[stage_index]]
        ).astype(np.float32)
        result[f"predicted_stage_{modality}"] = stage_index + 1
        return result

    target_names = manifest["primary_targets"]
    feature_rows: dict[str, list[np.ndarray]] = {}
    capture_ids: list[str] = []
    labels: list[list[float]] = []
    stage_rows: list[dict[str, str | int]] = []

    for group_index, group in enumerate(manifest["groups"], start=1):
        full_by_camera: dict[str, np.ndarray] = {}
        crop_by_camera: dict[str, np.ndarray] = {}
        for camera in range(1, 5):
            camera_key = str(camera)
            source_paths = [Path(path) for path in group["selected_images"][camera_key]]
            entries = [entry_lookup[str(path).lower()] for path in source_paths]
            crop_paths = [
                generated_path(entry["crop_path"], baseline_root) for entry in entries
            ]
            full_by_camera[camera_key] = encode(source_paths)
            crop_by_camera[camera_key] = encode(crop_paths)

        full_features = aggregate(full_by_camera, "full")
        crop_features = aggregate(crop_by_camera, "crop")
        for name, value in {**full_features, **crop_features}.items():
            if name.startswith("predicted_stage_"):
                continue
            feature_rows.setdefault(name, []).append(value)  # type: ignore[arg-type]

        capture_ids.append(group["capture_id"])
        labels.append([float(group["labels"][target]) for target in target_names])
        stage_rows.append(
            {
                "capture_id": group["capture_id"],
                "predicted_stage_full": int(full_features["predicted_stage_full"]),
                "predicted_stage_crop": int(crop_features["predicted_stage_crop"]),
            }
        )
        print(
            f"[{group_index}/{len(manifest['groups'])}] {group['capture_id']} "
            f"stage full/crop={stage_rows[-1]['predicted_stage_full']}/"
            f"{stage_rows[-1]['predicted_stage_crop']}"
        )

    arrays = {name: np.stack(rows) for name, rows in feature_rows.items()}
    np.savez_compressed(
        output_path,
        **arrays,
        y=np.asarray(labels, dtype=np.float64),
        capture_ids=np.asarray(capture_ids),
        target_names=np.asarray(target_names),
        text_embeddings=text_embeddings,
    )
    metadata = {
        "clip_model": args.model,
        "device": str(device),
        "manifest": str(manifest_path),
        "groups": len(capture_ids),
        "images_per_group": 24,
        "stage_prompts": stage_prompts,
        "stage_predictions": stage_rows,
        "feature_shapes": {name: list(array.shape) for name, array in arrays.items()},
    }
    metadata_path = output_path.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Features: {output_path}")
    print(f"Metadata: {metadata_path}")
    for name, array in arrays.items():
        print(f"  {name}: {array.shape}")


if __name__ == "__main__":
    main()
