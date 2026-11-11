# 模型發布範圍

## 固定 CLIP＋DINOv2 融合（主要版本）

`clip_dinov2/` 包含完整推論程式及兩組已擬合模型：

| 目錄 | 內容 | 答案來源 |
| --- | --- | --- |
| `artifacts/legacy9` | 9 筆全資料擬合的 PCA／Ridge 與 5 個視角選擇網路 | 原廠 CSV |
| `artifacts/native11` | 擴充至 11 筆的相同模型 | 原廠 CSV |

兩者骨幹均凍結、CLIP／DINO 預測固定各占 50%。這是新增保存的全資料模型，與歷史留一驗證的每折模型不同；不把訓練誤差當作驗證成績。11 筆集合包含 6/20 的 44 分 48 秒時間候選與 8/12 的 1 秒差配對，配對條件仍需保留在研究紀錄中。

`regressors.joblib` 需配合所記錄的 scikit-learn 版本。僅載入信任來源的序列化模型。

## 實驗性部分骨幹微調

四個權重在 [v0.1.0 Release](https://github.com/qwqohmy/greenhouse_project/releases/tag/v0.1.0)：

| 權重 | 影像前處理 | 輸出標籤 |
| --- | --- | --- |
| `rgb_native.pt` | 原始 RGB，完整畫面等比縮放補黑邊 | 7 個原廠數值 |
| `rgb_proxy.pt` | 原始 RGB，完整畫面等比縮放補黑邊 | `pGH_proxy,pMW_proxy` |
| `sam_native.pt` | SAM 處理後有效視角，等比縮放補黑邊 | 7 個原廠數值 |
| `sam_proxy.pt` | SAM 處理後有效視角，等比縮放補黑邊 | `pGH_proxy,pMW_proxy` |

這四個是先前實驗的權重，非這次重新進行大型訓練。發布前只移除工作機上的私人路徑等操作設定，參數張量保持相同。`models/export_report.json` 記錄大小、SHA256 與張量一致性檢查。

下載權重後，用 `experimental_adapter/predict.py`。`--input-json` 是 `{"views":[{"camera":"1","rgb_crop":"image.jpg"},...]}`，相對圖片路徑相對於該 JSON。RGB 固定視角版本需 12 或 24 張且各相機數量一致；SAM 版本可用 1–24 張，每相機最多 6 張。需依各權重實際輸入前處理提供圖片。

```powershell
python models/experimental_adapter/predict.py --input-json input.json --adapter rgb_native.pt --output prediction.json
```

預設下載官方骨幹。離線時設定 `CLIP_CACHE`、`DINO_REPO`、`DINO_WEIGHTS`。所有推論均不讀取答案 CSV／PLY，不生成點雲。

## 評估界限

既有 9／11 筆結果採留一觀測驗證，不代表獨立植株或獨立批次測試。其他 RGB／SAM 微調比較的資料子集、選圖及標籤來源不同，不能把不同集合的數字當作同條件排行榜。PLY 代理值的尺度、座標方向及與原廠指標的一致性尚待驗證。凍結特徵融合、原廠指標與 PLY 代理量在程式和說明中分開保存。
