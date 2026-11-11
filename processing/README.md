# 分割、PLY 衍生值與配對審核

`pipeline/` 保留本專案的 SAM RGB 批次處理、PLY 幾何分區與 CSV 輸出、時間候選與配對審核程式。`split_ply_observations.py` 可從點雲候選區域計算幾何代理值；`split_raw_ply_proposals.py` 依已驗證的座標轉換處理原始 PLY。

幾何連通區不必然等於一株植物，多株接觸也可能無法分離。因此輸出保留候選／審核狀態；不會把一份 CSV 的平均值複製到各株當作個別答案。`pGH_proxy`、`pMW_proxy` 和點法向傾角等量，不能直接當作已校準原廠株高、直徑或葉角。

這些批次程式使用原始工作流程的 catalog、配對 review、座標 registration JSON 及真實影像／PLY 路徑；私人輸入 manifest 不隨 GitHub 上傳。需取得對應資料、確認路徑與審核規則後才能重跑。可透過 `RGB_SAM_ROOT`／`SAM_ROOT` 指定分割輸出根目錄。

SAM 需另依上游授權安裝，其程式和權重不包含在本倉庫。單株身份對應仍需人工確認或其他可驗證證據，不能只憑同場次的區塊排序宣稱已驗證。
