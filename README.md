# Greenhouse Project

萵苣／番茄影像資料整理、單株配對，以及多視角 RGB → 植物表型數值的研究程式。
模型直接輸出數值 CSV，不以產生點雲為目標。本次發布範圍為 **2D→3D 表型模型、資料庫網站連結及相關程式碼**；不含 ConvNeXt 病蟲害模型。

## 資料庫網站

| 網站 | 內容 |
| --- | --- |
| [2D→3D 資料庫](https://foto-means-rendered-ensuring.trycloudflare.com/s/qDiiDCQACNOca9kx6LVDRSEUhiOCfbJj/) | 影像、原廠／PLY 衍生數值、配對狀態與 CSV 查詢 |
| [SAM 單株多光譜資料庫](https://invited-johnston-focused-luis.trycloudflare.com/s/CzPsCiT2eoBiUoBFT2tTPD_SH4nJHvUb/) | 批次、日期、光照、盆號、16 波段、遮罩與 NDVI 查詢 |

這兩個網址為遠端主機提供的 **臨時唯讀連結**，需主機、網站程序與 Cloudflare tunnel 持續運作。停止或重建 tunnel 後網址可能變更。依專案負責人要求，GitHub **僅提供資料庫連結與結構／程式碼，不上傳資料庫內容、SQL 資料備份或原始影像**。

## 模型與結果

一筆樣本是「某天、某株植物的多角度 RGB 影像 → 該株的一組表型答案」，24 張視角仍是一筆樣本。

| 方法／資料 | 原廠 CSV 樣本數 | MAE／平均值基準 | 平均 R² |
| --- | ---: | ---: | ---: |
| CLIP＋DINOv2 固定各 50%，歷史最佳 | 9 | 0.5837 | 0.4947 |
| 同方法重新擷取特徵重跑 | 9 | 0.5839 | 0.4943 |
| 同方法擴充原廠 CSV | 11 | 0.7134 | 0.3419 |

以上是**留一觀測交叉驗證**，MAE／基準越低越好，0.5837 並非準確率。樣本很少，驗證結果仍不穩定；也未證明跨植株、跨批次的泛化能力。不同樣本集合的平均值基準不同，不能把兩個比值的差直接當作新增資料造成的退步。

最佳方法使用凍結的 CLIP ViT-B/32 與 DINOv2 ViT-S/14，只訓練回歸器與小型視角選擇網路。`models/clip_dinov2/artifacts` 另提供用全部 9／11 筆重新擬合的可推論模型，**這些全資料模型本身沒有獨立測試成績**。

先前 RGB／SAM 的部分骨幹微調權重另放 [GitHub Releases](https://github.com/qwqohmy/greenhouse_project/releases/tag/v0.1.0)，屬實驗比較，未優於上述歷史小樣本結果。見 [模型說明](models/README.md)。

## 開始使用

```powershell
conda env create -f environment.yml
conda activate greenhouse
python -m pip install -r requirements.txt
python models/clip_dinov2/predict.py --model models/clip_dinov2/artifacts/legacy9 --image-folder "D:/data/one_capture" --output "prediction.csv"
```

單一資料夾內需有 `CAM1_*` 至 `CAM4_*` 的 JPG／PNG；程式依檔名排序，各取 6 個等距拍攝序號，共 24 張。順序須與原始轉台拍攝順序一致。第一次推論會下載官方 CLIP／DINOv2 預訓練權重；亦可指定本地快取，見 [推論說明](models/clip_dinov2/README.md)。

輸出為 `pGH, pTLA, pPLA, pLAA, pCHA, pE, pMW` 七個原廠欄位。原廠座標尺度／物理單位尚未獨立校準，輸出保留 `VENDOR_UNIT_UNVERIFIED`；PLY 的幾何代理量則維持不同欄位，不能當作同一份標籤混訓。

## 專案目錄

- `models/`：最佳融合方法、已擬合模型、小型回歸／視角選擇網路訓練、實驗微調模型推論。
- `experiments/`：歷史特徵擷取、交叉驗證、RGB／SAM 與 XGBoost 比較程式。部分流程需原始工作目錄與私人資料 manifest，見該目錄說明。
- `databases/`：網站連結、MySQL 結構、匯入／查詢／唯讀網站程式；無資料內容或連線帳密。
- `processing/`：分割、PLY 衍生幾何值與配對審核程式。
- `tools/portable_database.py`：可選的唯讀匯出／空資料庫還原工具，不包含任何匯出資料。
- `licenses/`：CLIP、DINOv2 上游授權文件。

多光譜目前有 5,940 筆單株觀測，其中 5,933 筆有可計算的 NDVI。公式為 `(L800-L680)/(L800+L680)`，在遮罩內逐像素計算再彙總。目前來源為**未校準的原始 DN 值**，不能直接宣稱是經反射率校準的 NDVI，也不是健康標籤；高藍光下 NDVI 高不等於鮮重高。

本專案自有程式採 [MIT](LICENSE)，上游模型各依原授權，詳見 [第三方說明](THIRD_PARTY_NOTICES.md)。原始影像、原廠資料及專家標註的權利不由本程式授權重新授予。
