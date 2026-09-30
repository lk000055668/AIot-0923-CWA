# Map-first 氣象地圖

啟動：`.\.venv\Scripts\python.exe -m streamlit run app.py`

## 操作

- 左上切換單一主要圖層：氣溫、濕度、雨量、風速。只列出載入資料中至少有一筆有效觀測的項目。
- 三個 checkbox 可獨立疊加測站位置、縣市界線、行政區界線。測站位置為獨立位置圓點；不影響主要氣象標籤原有的縮放分層。
- 左下圖例與 marker、popup、目前層級的 polygon 著色共用同一份色階定義。色階兩端包含超出範圍的觀測；滑鼠移到色塊可看區間。
- zoom ≤ 8：縣市；8 < zoom ≤ 10：行政區；zoom > 10：仍顯示行政區名稱與平均觀測。測站僅作為可選來源圓點，不會變成主要標籤。縣市／行政區數值是有值測站平均，雨量也使用平均，不是全區總雨量或插值。
- 上方搜尋框支援中文部分比對、台／臺正規化、測站代碼、方向鍵／Enter／Escape。搜尋使用已載入的界線與測站，不另呼叫 CWA。搜尋排序優先縣市、其次行政區、最後測站來源。點行政區結果會定位並打開區域觀測 popup，含各欄位有效站數與可展開的原始測站讀數。點測站結果仍可定位，popup 以行政區為標題，明確標示該站讀數不是行政區平均。
- 右上概況顯示目前最高／最低溫與地點、最大雨量與地點、最新觀測時間；平均溫、最大風速收在其他統計。無資料的指標不顯示。警報未取得與零警報分開顯示。
- 資料與設定保留 API Key、自動／手動同步、測站表、CSV 及 Plotly 預報。

## 結構與資料原則

`app.py` 使用既有 CWA → data_processor → SQLite 流程，無示範、random 或 hard-coded 氣象值。沒有觀測時顯示空地圖狀態，仍可使用真實行政界線搜尋。`data_processor.py` 與 `database.py` 只修正缺測值不再轉成 0；真實的 0 保留。API 模組、DB schema、預報圖表與既有 zoom 閾值未改。

`spatial_mapping.py` 以 longitude / latitude 對行政區 Polygon / MultiPolygon 做 point-in-polygon，處理 polygon 孔洞與共用邊界；利用 bounding box 預篩選並快取座標結果。`map.py` 先從 GeoJSON 建立完整區域清單，縣市依原始 CWA 縣市欄位聚合，行政區依 mapping 結果聚合；所有指標走 `assets/weather-renderer.js` 同一個 zoom / move handler。測站即使缺氣溫，也可貢獻濕度等有值欄位的行政區平均。無座標測站保留於聚合及 Popup 來源，但無法提供測站位置搜尋。`map_ui.py` 和 `assets/weather-map.js` 負責控制 UI，不另建一套氣象處理。色階由 `WEATHER_LAYERS` 定義，只有有效資料才啟用。

主要 UI 都在 Leaflet iframe 裡，圖層／overlay／搜尋不觸發 Streamlit rerun。設定按鈕固定於宿主頁面並開啟 dialog。sessionStorage 保存視角、圖層與 overlay；存取被瀏覽器禁用時仍能操作，但不保存。

## 圖資與限制

原專案沒有 GeoJSON。本次加入 22 縣市與 368 鄉鎮市區界線：Taiwan Atlas 2021.9.20，衍生自內政部國土測繪中心資料。這是附帶的參考圖資版本，非即時行政區更新服務。來源、版本與授權詳見 [assets/BOUNDARIES.md](assets/BOUNDARIES.md) 及 MIT 授權檔。GeoJSON 在本地載入；搜尋不下載圖資。沒有觀測的區域只有界線，不填造天氣值。

沒有歷史觀測快照，因此不提供歷史／未來日期圖層。底圖維持 OSM，深色以 tile-pane filter 呈現；Leaflet 與 OSM 圖磚需要網路。界線約 2.6 MB，隨 iframe 載入一次；之後互動不需重載頁面。未增加 app 執行依賴。原 `mapc.py` 備份檔未修改，也未被 app 使用。

## 驗證

- `.\.venv\Scripts\python.exe -m pytest -q`：包含缺测 NULL 與真零 SQLite roundtrip、各指標獨立聚合、空資料與注入防護。
- `python tests/browser_map_ui.py`：需開發用 Playwright 與 Edge，直接啟動實際 app，用既有 CWA 金鑰同步 SQLite，檢查 1920×1080、1440×900、1366×768、390×844；四種圖層、每個 zoom 臨界值、三個 overlay、polygon 著色、動態圖例、真實摘要、搜尋與 popup、CSV、預報、視角保存、runtime / console error。完成後關閉測試服務。
- `python tests/browser_map_ui.py --empty`：隔離空資料情境，不接觸正式 DB 或 API；檢查不顯示氣象選項／值／圖例，界線與搜尋仍可操作。

瀏覽器成功驗證的實際畫面保存在 `assets/map-first-preview.png`。

## 行政區 mapping 與來源可追溯性

每站保留 `sourceCountyName` / `sourceTownName` 與原始測站讀數，另以 `countyName` / `townName` 記錄座標判定結果。未修改 CWA API、資料庫 schema 或原始資料；mapping 用於地圖 payload。

- `polygon`：座標唯一落入一個行政區，優先於 CWA 文字欄位。
- `boundary_cwa`：共用邊界同時命中多區，以 CWA 已提供的縣市／行政區欄位確認其中一區。
- `cwa_fallback`：座標未落入參考圖資，例如未涵蓋的外海島嶼；只採用 CWA 已提供且存在於圖資的縣市／行政區欄位，不猜測站名、不找最近行政區。
- `ambiguous` / `unmapped`：無法確認，保留來源站供查看，不加入行政區平均。

各氣象指標各自忽略缺測值取算術平均，僅有一站時即為該站讀數；雨量亦為測站平均，非全區總量。`counts` 記錄每個指標的有效站數，`station_ids` 保留區域全部來源。Popup 可展開來源測站的各項原始讀數與觀測時間；fallback 另有說明。

標籤跨氣象圖層使用穩定的 polygon 內部代表點，縣市與行政區都不使用測站座標。沿用現有 geometry helper 處理 MultiPolygon 與孔洞。有效區域全部保留 marker，縮放只切換縣市／行政區 layerGroup；平移不刪除區域標籤。測站位置疊加仍按視窗篩選。快取會在界線檔更新時失效。

`map.weather.debug()` 回傳目前圖層／層級的完整數量、NO DATA 清單及逐區 trace。`MARKERS_RENDERED` 實際檢查 Leaflet layer 與 DOM 連線；`in_view` 另行記錄是否在視窗內。非目前層級以 `ACTIVE: false` 標示，避免將縮放時刻意隱藏的另一層級誤判為缺失。驗證結果與全部無有效氣溫行政區清單見 [LABEL_DEBUG_REPORT.md](LABEL_DEBUG_REPORT.md)。

本次實際資料驗證：363 站，360 站直接 point-in-polygon 定位，3 站使用 CWA 既有欄位 fallback。新增 Polygon、MultiPolygon、孔洞、共用邊界、錯誤來源名稱、缺测聚合、單站與標籤位置測試；瀏覽器測試覆蓋 zoom 8 / 8.5 / 10 / 10.5 / 12 / 14 及「淡水／西屯／信義」搜尋。
