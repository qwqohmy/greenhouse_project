# 資料庫網站與原始碼

- [2D→3D 表型資料庫](https://twice-garage-changing-price.trycloudflare.com/s/qDiiDCQACNOca9kx6LVDRSEUhiOCfbJj/)
- [SAM 單株多光譜／NDVI 資料庫](https://wayne-import-eminem-colony.trycloudflare.com/s/CzPsCiT2eoBiUoBFT2tTPD_SH4nJHvUb/)

連結更新日期：2026-11-19。

首頁目前為三欄影像圖庫，可切換生菜與番茄，下載整張示例或每筆獨立JPG。原本查詢頁面在分享前綴後的 `records`，既有 API、圖片與 CSV 路由保持不變。

圖庫的單位為「植株×拍攝日期」，同株跨日可分別展示，同日不同角度／波段不重複充作樣本。現展示生菜2D 12筆、番茄2D 10筆、多光譜兩種作物各12筆；番茄2D不足的兩格明示待補。圖庫展示資料以允許清單索引管理，**番茄尚未新增到原單株MySQL表或完成表型答案配對**，不能把展示筆數當成訓練就緒筆數。

`app/dataset_gallery.py` 只允許讀取 `app/web-runtime/gallery/manifest.json` 中登記的JPG。版面程式為 `gallery.html/css/js`；來源圖片與部署索引均不納入GitHub。索引結構和部署方式見 [圖庫部署說明](GALLERY.md)。

依專案負責人要求，資料庫內容**只透過網站連結提供**，不放 SQL 資料備份、JSON 資料快照或原始圖片。網站的 CSV 下載仍依既有唯讀介面提供。連結為臨時 tunnel，可能因遠端重啟而失效。

`plant_2d3d/schema.sql` 是目前 16 個表及 3 個檢視表的結構；`plant_multispectral/schema.sql` 是目前 11 個表及 2 個檢視表的結構，皆不含資料列。`legacy_multispectral/source/` 為舊版整張多光譜索引的歷史程式，與新版單株資料庫分開。

建立空結構可在 MySQL 8.0+ 的空白資料庫中執行各 `schema.sql`。原始資料與影像不會因建表自動出現；需另行取得、準備 manifest 並執行對應匯入程序。

新版 NDVI 為遮罩內逐像素 `(L800-L680)/(L800+L680)` 後彙總；排除分母為零、飽和與無效像素，空遮罩記錄空值。來源是原始 DN，反射率校準與跨波段配準未獨立驗證，不能直接作健康真值。第 2 批是批次編號，該批每光 21 株；第 1 批每光 12 株。

## 本地部署

網站程序皆只綁定 `127.0.0.1`。網站設定與隨機分享 token 於本地產生並被 `.gitignore` 排除，不使用正式站的帳密。

- 多光譜：設定 `MYSQL_HOST,MYSQL_PORT,MYSQL_USER,MYSQL_PWD`，首次建立唯讀帳號另需 `MYSQL_ROOT_PASSWORD`；`SAM_ROOT` 指向單株 PNG 根目錄，`LEGACY_SPECTRAL_ROOT` 指向原始多光譜圖片。於 `plant_multispectral/app` 執行 `python setup_viewer.py`、`python viewer.py`。
- 2D→3D：設定 `P3D_MYSQL_HOST,P3D_MYSQL_PORT,P3D_MYSQL_DATABASE`，首次建立唯讀帳號需 `MYSQL_ROOT_PASSWORD`；`RGB_ROOT,RGB_SAM_ROOT,PLY_ROOT,PIPELINE_ROOT,OCTOBER_RGB_ROOT` 對應原始素材根目錄。於 `plant_2d3d/app` 執行 `python setup_viewer.py`、`python viewer.py`。

資料匯入、配對審核腳本需操作帳號的 `MYSQL_PWD`；唯讀網站使用獨立 SELECT 帳號。歷史工作流程所需的 manifest 及配對審核資料不在此倉庫，詳見 `experiments/README.md`。`tools/portable_database.py` 是可選工具，不會自動連線正式資料庫，也不附任何帳密或資料匯出。
