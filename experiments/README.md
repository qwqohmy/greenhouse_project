# 歷史研究程式

此目錄保留原始比較實驗的訓練、特徵擷取、留一驗證與 RGB／SAM 比較程式。這些是專案的適配程式，並非宣稱完整重現同名論文的原始任務。

`CLIP-MVP/adapter` 使用 CLIP 特徵；`ViewSparsifier-DINOv2/adapter` 使用 DINOv2 多視角特徵並比較固定融合；`RGBD-RF-XGBoost/adapter` 是影像／深度統計與傳統回歸比較；`CLIP-DINOv2-Finetune` 為後續的原方法重跑、擴充原廠 11 筆及部分骨幹微調實驗。

歷史腳本依賴原始工作目錄的 `outputs/manifest.json`、答案 CSV、影像、深度快取、資料庫的配對狀態與固定人工審核資料。有些腳本假設此目錄相鄰有 `ResNet18-DepthAnything-Fusion` 及 `database`；這些私人資料與生成物不隨 GitHub 發布。需要自行還原工作目錄或調整腳本中的 ROOT／manifest 輸入，不能直接把缺資料的歷史腳本當成開箱即用訓練。

對外推論使用 `models/` 的獨立入口，不依賴原工作目錄。若已有同格式特徵，可用 `models/clip_dinov2/train.py` 訓練新模型。數據單位、近時間候選配對及樣本數的限制見主 README。
