# Third-party code and models

Project-authored source code: MIT, see `LICENSE`. This license does not relicense upstream code, checkpoints, images or vendor measurements.

| Component | Upstream | License / distribution in this repository |
| --- | --- | --- |
| CLIP ViT-B/32 | https://github.com/openai/CLIP | MIT; upstream license included in `licenses/CLIP-LICENSE`. Full upstream checkpoint downloaded separately. Experimental adapters contain derived last-block tensors, subject to this notice. |
| DINOv2 ViT-S/14 | https://github.com/facebookresearch/dinov2 | Apache-2.0; upstream license included in `licenses/DINOv2-LICENSE`. Full upstream checkpoint downloaded separately. Experimental adapters contain derived last-block tensors; our regression/selection modules and fine-tuned tensors are modifications for numeric plant-trait regression. |
| PyTorch / torchvision | https://github.com/pytorch/pytorch | BSD-style licenses; installed separately. |
| scikit-learn | https://github.com/scikit-learn/scikit-learn | BSD-3-Clause; installed separately. |
| PyMySQL | https://github.com/PyMySQL/PyMySQL | MIT; installed separately. |
| MySQL Community Server | https://www.mysql.com/products/community/ | GPL; server binary is not redistributed. |
| SAM 3.1 preprocessing | https://github.com/facebookresearch/sam3 | External prerequisite under its upstream SAM license, not represented here as MIT/Apache or OSI-approved. SAM weights and upstream SAM implementation are not redistributed. |

The frozen CLIP/DINO models' regression and selection artifacts are project-specific fitted components; use with the original encoders and preserve the above notices. Large experimental adapter release assets are modifications of CLIP/DINO last blocks, not standalone encoders. The original images, vendor CSVs, harvest sheets and annotation rights remain with their respective owners and are not included in the Git repository.

The database site URLs are intentionally shared read-only access links, explicitly authorized by the project owner. They are not MySQL credentials. No operational passwords, private configuration or MySQL data directory is distributed.
