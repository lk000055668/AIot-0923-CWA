# 氣象標籤修正與實測報告

本次固定快照：363 個 CWA 測站，觀測時間 2026-09-30T16:00:00+08:00 ～ 2026-09-30T16:00:00+08:00。
修正前與修正後使用完全相同的 SQLite 觀測快照，避免 API 更新造成比較失真。
另有啟動原始 `app.py` 並實際同步 CWA 的完整 UI 回歸，皆已通過。

## 根因與修正

1. 舊 `assign_station_districts()` 以 GeoJSON 的「台北市／台中市／台南市／台東縣」覆寫 CWA 的「臺」字縣市名稱。`_build_county_markers()` 的 `REGION_COORDINATES` 僅接受「臺」字，四個縣市在 marker 資料建立前被 `continue` 排除。不是 CWA 無資料。
2. 舊縣市彙整依賴行政區 spatial join 的結果。現在縣市直接依保留的原始 `sourceCountyName` 聚合，行政區依座標 mapping；兩者獨立 join GeoJSON 的完整區域清單。
3. 舊 `sync()` 在建立 marker 前以 padded viewport 篩選，也在平移時移除視窗外 marker。這是視窗裁切，不是碰撞避讓；因此不能把所有未建立的行政區稱為「畫面內消失」。現在有效區域 marker 全部保留，縮放只切換 county／district LayerGroup，視窗外 marker 留在 DOM、隨地圖自然裁切。
4. 未發現 collision／declutter／minimum-distance 演算法，也未發現建立後被另一函式誤清除的情況。`setMetric()` 清除舊 metric 後立即完整重建；stress test 沒有累積缺失。
5. 原先 parser 與 map preparation 丟棄缺座標站。現在保留其有效觀測供縣市聚合；行政區只有在 CWA 明示名稱可確認時 fallback，不用鄰區補值。
6. 縣市與行政區使用 GeoJSON 內部代表點，沿用現有 `DistrictIndex.label_point()`，不取測站座標或 bounds center。390 個區域代表點全部通過 polygon covers 驗證。
7. `normalizeCountyName()`／`normalizeDistrictName()` 統一 NFKC、空白及「台／臺」，涵蓋 CWA、GeoJSON、mapping、aggregation 與前端搜尋／rendering。

## 修正前後數量

1440×900，中心 [23.75, 120.95]；縣市 zoom 7.5、行政區 zoom 9。數量分別在其層級啟用時量測。
`MARKERS_RENDERED` 是同時存在 Leaflet map 與 DOM 的 marker 數；是否位於視窗內另列 `in_view`，不將 overlap 當成未渲染。

| 時點／層級 | TOTAL_REGIONS | WITH_VALID_DATA | MARKERS_CREATED | MARKERS_RENDERED | MISSING |
| --- | ---: | ---: | ---: | ---: | ---: |
| 修正前／縣市 | 22 | 22 | 18 | 18 | 4 |
| 修正後／縣市 | 22 | 22 | 22 | 22 | 0 |
| 修正前／行政區 | 368 | 211 | 187 | 187 | 24（視窗篩選） |
| 修正後／行政區 | 368 | 211 | 211 | 211 | 0 |

舊縣市 payload 本身只剩 18 項，因此 WITH_VALID_DATA 依原始 CWA 重新計算為 22，不能錯算為 18。
修正後 `MISSING: []`；不存在有有效氣溫卻未加入啟用中 LayerGroup／DOM 的區域。

## 原本有資料但缺少 marker 的區域

縣市：臺北市、臺中市、臺南市、臺東縣（名稱比對失敗）。

以下 24 個行政區在上述 zoom 9 測試視角被 viewport 篩選，清單會隨原本視角改變；它們的 weather data、aggregation 都存在，消失階段為 `sync()` → marker creation。

| 縣市 | 行政區 |
| --- | --- |
| 基隆市 | 七堵區、中山區、中正區、仁愛區 |
| 屏東縣 | 恆春鎮、春日鄉、林邊鄉、牡丹鄉、車城鄉 |
| 新北市 | 三重區、汐止區、泰山區、淡水區、瑞芳區、石門區 |
| 桃園市 | 蘆竹區 |
| 臺北市 | 北投區、士林區 |
| 臺東縣 | 大武鄉、蘭嶼鄉 |
| 連江縣 | 南竿鄉、東引鄉 |
| 金門縣 | 金城鎮、金湖鎮 |

## 本快照沒有有效氣溫的行政區

縣市：無。行政區：157 個。這只表示此快照沒有有效 CWA 氣溫，不代表永久沒有氣象站。
沒有 fake／random／鄰近行政區補值，也沒有特定縣市 if/else。

### 有來源站，但所有氣溫缺測（6 個）

| 縣市 | 行政區 |
| --- | --- |
| 基隆市 | 安樂區 |
| 桃園市 | 大園區 |
| 澎湖縣 | 白沙鄉 |
| 雲林縣 | 二崙鄉 |
| 高雄市 | 橋頭區、茂林區 |

### 沒有映射到來源站（151 個）

| 縣市 | 行政區 |
| --- | --- |
| 南投縣 | 南投市、水里鄉、集集鎮 |
| 嘉義縣 | 六腳鄉、太保市、番路鄉 |
| 基隆市 | 信義區、暖暖區 |
| 宜蘭縣 | 蘇澳鎮、頭城鎮 |
| 屏東縣 | 三地門鄉、佳冬鄉、來義鄉、崁頂鄉、新園鄉、枋寮鄉、枋山鄉、滿州鄉、潮州鎮、獅子鄉、琉球鄉、瑪家鄉、萬丹鄉、里港鄉、霧臺鄉、高樹鄉、鹽埔鄉、麟洛鄉 |
| 彰化縣 | 二水鄉、伸港鄉、員林市、埔心鄉、埤頭鄉、永靖鄉、溪州鄉、溪湖鎮、田尾鄉、社頭鄉、福興鄉、秀水鄉、線西鄉、芬園鄉、花壇鄉 |
| 新北市 | 三峽區、三芝區、中和區、五股區、八里區、新莊區、板橋區、林口區、永和區、深坑區、萬里區、蘆洲區、金山區、雙溪區 |
| 新竹市 | 北區 |
| 新竹縣 | 北埔鄉、尖石鄉、橫山鄉、竹東鎮、芎林鄉 |
| 桃園市 | 龜山區 |
| 澎湖縣 | 七美鄉、湖西鄉 |
| 臺中市 | 中區、北屯區、南區、南屯區、外埔區、大安區、大里區、大雅區、東勢區、東區、梧棲區、潭子區、石岡區、西區、豐原區 |
| 臺北市 | 中山區、信義區、內湖區、大同區、松山區、萬華區 |
| 臺南市 | 仁德區、佳里區、北區、南區、學甲區、安定區、安平區、將軍區、山上區、左鎮區、東區、柳營區、歸仁區、西港區、鹽水區、龍崎區 |
| 臺東縣 | 延平鄉、池上鄉、海端鄉、綠島鄉、達仁鄉、金峰鄉 |
| 花蓮縣 | 光復鄉、壽豐鄉、新城鄉、萬榮鄉、豐濱鄉 |
| 苗栗縣 | 三灣鄉、泰安鄉 |
| 連江縣 | 北竿鄉、莒光鄉 |
| 金門縣 | 烈嶼鄉、烏坵鄉、金寧鄉、金沙鎮 |
| 雲林縣 | 北港鎮、大埤鄉、斗六市、東勢鄉、水林鄉、莿桐鄉、褒忠鄉 |
| 高雄市 | 三民區、前金區、前鎮區、大寮區、大社區、小港區、左營區、彌陀區、新興區、林園區、桃源區、梓官區、永安區、湖內區、燕巢區、苓雅區、茄萣區、那瑪夏區、阿蓮區、鳳山區、鹽埕區、鼓山區 |

## Debug trace 與驗證

- [label_trace.csv](label_trace.csv)：390 個區域逐一記錄 region exists、來源站數、有效氣溫數、聚合值、geometry、代表點、修正前 marker／layer 狀態、缺失階段、修正後 marker／layer／DOM 狀態。
- 本機 `data/label-audit/browser-report.json`：完整瀏覽器 trace、47 個檢查點及 console／runtime error 清單（空）。此目錄為本機驗證產物，已排除 Git。
- 本機 `data/label-audit/observations.json`、`before.html`、`before-payload.json`：固定原始快照與舊版重現頁。
- `map.weather.debug()`：在 Leaflet iframe console 呼叫；可指定 `county`／`district`，非目前層級標示 `ACTIVE: false`。
- `python -m pytest tests/ -q`：30 passed；包含 Polygon、MultiPolygon、洞、共邊、錯誤來源、缺值、真零、缺座標與全部 geometry anchor。
- `python tests/browser_label_completeness.py`：47 個檢查點，包括全台、五輪 zoom in/out、平移、四種 Weather Layer、zoom 邊界、overlay、搜尋及 Popup；每次都檢查 WITH_VALID_DATA = MARKERS_CREATED = MARKERS_RENDERED。
- `python tests/browser_map_ui.py`：實際 Streamlit + CWA + SQLite，四個螢幕尺寸、圖例、摘要、搜尋、Popup、CSV、預報與設定保存通過；JS／console errors 均為空。
- `python tests/browser_map_ui.py --empty`：無資料時沒有假氣象值，搜尋與界線正常；沒有 JS／console error。
- 本機沒有 Node.js，因此未執行 `node --check`；兩個 JavaScript 檔案已在 Edge 的實際頁面執行通過。

## 修改檔案與函式

| 檔案 | 函式／變更 |
| --- | --- |
| `region_names.py`（新增） | `normalizeCountyName()`、`normalizeDistrictName()` |
| `data_processor.py` | `parse_realtime_station_json()`：名稱正規化、保留缺座標觀測 |
| `spatial_mapping.py` | `DistrictIndex.__init__()`、`normalized()`：canonical region keys，縣市 geometry 也可沿用索引 |
| `map.py` | `prepare_map_observations()`、`_load_boundaries_cached()`、`build_weather_payload()`：Region-first、raw county join、逐指標聚合、幾何代表點、NO DATA |
| `assets/weather-renderer.js` | `sync()`、`updateWeatherLayers()`、新增 `debug()`、canonical naming、搜尋索引座標檢查 |
| `tests/test_label_completeness.py`（新增） | 四項資料及完整區域 regression tests |
| `tests/browser_label_completeness.py`（新增） | 同快照修正前後瀏覽器驗證與逐區 trace |
| `UI_NOTES.md`、`LABEL_DEBUG_REPORT.md`、`label_trace.csv` | 更新流程說明、完整報告及數據 |
| `.gitignore` | 排除本機比較頁面、快照與測試伺服器產物 |

保留 Map-first UI、Leaflet、CWA API、GeoJSON、Weather Layer Control、Legend、Summary、Search、Popup 與既有 zoom 閾值。小區域標籤仍可能重疊，符合本次優先完整渲染的要求。
