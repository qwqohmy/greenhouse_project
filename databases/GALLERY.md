# 影像圖庫部署

每個app目錄包含相同的 `dataset_gallery.py`、`gallery.html`、`gallery.css`、`gallery.js`。分享前綴下的首頁和 `gallery` 顯示圖庫；`records` 顯示原本查詢頁面。

圖庫完全唯讀，不修改MySQL表。影像、來源配置和私有部署檔均未發布至GitHub。需取得影像後自行建立下列目錄：

```text
app/web-runtime/gallery/
  manifest.json
  lettuce_sheet.jpg
  tomato_sheet.jpg
  images/
    lettuce-20261015-pot01.jpg
    tomato-20261020-single.jpg
```

`manifest.json` 格式如下，以下僅示範欄位，不表示附有該影像：

```json
{
  "kind": "2d",
  "updated_on": "2026-11-19",
  "sample_unit": "plant-date observation",
  "rows": [
    {
      "id": "lettuce-20261015-pot01",
      "crop": "lettuce",
      "date": "2026-10-15",
      "plant_label": "當日第1盆",
      "channel": "RGB",
      "image_file": "images/lettuce-20261015-pot01.jpg",
      "observation_key": "lettuce-20261015-pot01"
    }
  ],
  "sheets": {"lettuce": "lettuce_sheet.jpg", "tomato": "tomato_sheet.jpg"}
}
```

多光譜站使用 `kind: "spectral"`，示例固定為540nm預覽，原始16位元PNG及NDVI計算不變。`crop` 僅接受 `lettuce` 或 `tomato`，每個觀測鍵唯一；不把不同角度或波段計為新的植株當日觀測。

路由：`api/dataset-gallery?crop=tomato`、`gallery/image/<id>`、`gallery/sheet/tomato`、`gallery/download/tomato.zip`。ZIP只含該作物已登記的個別JPG；無法讀取任意檔案或私有設定。圖庫數量、同株不同日期和表型訓練配對數必須分開解釋。

圖庫目前以12格展示，不足時留出明確標示的待補格；下載包只包含真實存在的影像，不包含待補格。
