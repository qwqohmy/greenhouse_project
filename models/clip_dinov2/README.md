# Frozen CLIP + DINOv2 phenotype regression

輸入：單株同次拍攝的四相機多角度 RGB；每相機依序取 6 張，共 24 張。輸出：七個原廠數值欄位的 CSV 與附帶來源／單位狀態的 JSON。

CLIP 使用官方影像轉換，取 24 個未做逐張 L2 正規化的 embedding 平均；各目標以 StandardScaler、PCA、RidgeCV 回歸。DINOv2 使用 Resize(256)、CenterCrop(224)、ImageNet 正規化及每視角 embedding 的 L2 正規化，PCA 後加入相機／俯側視／拍攝位置編碼，訓練五個不同種子的選擇網路。最終以固定 50/50 融合兩個分支的原尺度預測。

```powershell
python models/clip_dinov2/predict.py --model models/clip_dinov2/artifacts/legacy9 --image-folder "D:/data/one_capture" --output prediction.csv
```

原始圖片不必先由 SAM 裁切。輸入照片必須拍同一株；程式不會自動驗證實體盆號。歷史相機角色編碼為 CAM1／2 俯視、CAM3／4 側視；不同硬體配置需重新確認。

離線快取：

```powershell
python models/clip_dinov2/predict.py --model models/clip_dinov2/artifacts/legacy9 --image-folder "D:/data/one_capture" --output prediction.csv --clip-cache "D:/cache/clip" --dino-repo "D:/cache/dinov2" --dino-weights "D:/cache/dinov2_vits14_pretrain.pth"
```

從既有特徵訓練：

```powershell
python models/clip_dinov2/train.py --clip-features clip_features.npz --dino-features dinov2_view_features.npz --output my_model --epochs 800 --seeds 5
```

CLIP NPZ 需 `capture_ids, X_clip_full_mean (N,512), y (N,7)`；DINO NPZ 需 `capture_ids, X_views (N,24,384), y (N,7)`，ID 和答案順序必須完全相同。此指令用全部資料擬合，不產生驗證成績；交叉驗證需每折只在訓練資料擬合 PCA、標準化與回歸器，歷史程式見 `experiments/`。

模型訓練／載入所用的精確依賴版本見 `models/model_verification.json`。
