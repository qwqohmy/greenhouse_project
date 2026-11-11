from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract frozen per-view DINOv2 features for all clean capture groups."
    )
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="dinov2_vits14")
    parser.add_argument("--batch-size", type=int, default=24)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    args = parse_args()
    method_root = Path(__file__).resolve().parents[1]
    plant_root = method_root.parent
    baseline_root = args.baseline_root or plant_root / "ResNet18-DepthAnything-Fusion"
    output_path = args.output or method_root / "outputs" / "dinov2_view_features.npz"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TORCH_HOME", str(method_root / ".cache" / "torch"))
    os.environ.setdefault("PYTHONUTF8", "1")

    import numpy as np
    import torch
    from PIL import Image
    from torchvision import transforms

    manifest_path = baseline_root / "outputs" / "manifest.json"
    manifest = load_json(manifest_path)
    target_names = manifest["primary_targets"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = torch.hub.load(
        "facebookresearch/dinov2",
        args.model,
        pretrained=True,
        trust_repo=True,
    ).to(device)
    model.eval()
    preprocess = transforms.Compose(
        [
            transforms.Resize(256, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            ),
        ]
    )

    def encode(paths: list[Path]) -> np.ndarray:
        chunks: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(paths), args.batch_size):
                tensors = []
                for path in paths[start : start + args.batch_size]:
                    with Image.open(path) as image:
                        tensors.append(preprocess(image.convert("RGB")))
                batch = torch.stack(tensors).to(device, non_blocking=True)
                features = model(batch).float()
                features = torch.nn.functional.normalize(features, dim=-1)
                chunks.append(features.cpu().numpy())
        return np.concatenate(chunks).astype(np.float32)

    all_features: list[np.ndarray] = []
    all_paths: list[list[str]] = []
    labels: list[list[float]] = []
    capture_ids: list[str] = []
    camera_ids: list[int] = []
    role_ids: list[int] = []
    angle_ids: list[int] = []
    for camera in range(4):
        for angle in range(6):
            camera_ids.append(camera)
            role_ids.append(0 if camera < 2 else 1)
            angle_ids.append(angle)

    print(f"Device: {device}")
    print(f"DINOv2 model: {args.model}")
    for group_index, group in enumerate(manifest["groups"], start=1):
        paths = [
            Path(path)
            for camera in range(1, 5)
            for path in group["selected_images"][str(camera)]
        ]
        if len(paths) != 24:
            raise ValueError(f"{group['capture_id']} has {len(paths)} selected views")
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Missing images for {group['capture_id']}: {missing[:3]}")
        all_features.append(encode(paths))
        all_paths.append([str(path) for path in paths])
        labels.append([float(group["labels"][name]) for name in target_names])
        capture_ids.append(group["capture_id"])
        print(f"[{group_index}/{len(manifest['groups'])}] {group['capture_id']}")

    feature_array = np.stack(all_features)
    np.savez_compressed(
        output_path,
        X_views=feature_array,
        y=np.asarray(labels, dtype=np.float64),
        capture_ids=np.asarray(capture_ids),
        target_names=np.asarray(target_names),
        camera_ids=np.asarray(camera_ids, dtype=np.int64),
        role_ids=np.asarray(role_ids, dtype=np.int64),
        angle_ids=np.asarray(angle_ids, dtype=np.int64),
        image_paths=np.asarray(all_paths),
    )
    metadata = {
        "model": args.model,
        "device": str(device),
        "manifest": str(manifest_path),
        "groups": len(capture_ids),
        "views_per_group": 24,
        "feature_shape": list(feature_array.shape),
        "view_order": "CAM1 angles 0-5, CAM2 angles 0-5, CAM3 angles 0-5, CAM4 angles 0-5",
        "camera_roles": {"top": [1, 2], "side": [3, 4]},
    }
    output_path.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Features: {output_path}")
    print(f"Shape: {feature_array.shape}")


if __name__ == "__main__":
    main()
