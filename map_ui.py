"""Floating controls inside the existing Folium map; no network or fake values."""
from html import escape
from pathlib import Path
import folium
from branca.element import MacroElement, Template
from map import safe_json

ASSETS = Path(__file__).parent / "assets"
APP_CSS = """<style>
header[data-testid="stHeader"], [data-testid="stSidebar"], footer {display:none!important}
.stApp {background:#0b1220;color:#e2e8f0}
[data-testid="stMainBlockContainer"] {padding:0!important;max-width:none!important}
.st-key-weather_map {position:fixed!important;inset:0!important;height:100vh!important;height:100dvh!important;width:100vw!important;z-index:1;background:#0b1220}
.st-key-weather_map iframe {position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;height:100dvh!important;border:0!important}
.st-key-map_settings {position:fixed!important;left:22px;bottom:24px;width:auto!important;z-index:5}
.st-key-map_settings button {background:rgba(15,23,42,.85);color:#e2e8f0;border:1px solid #ffffff26;border-radius:12px;backdrop-filter:blur(16px);font-size:13px}
[data-testid="stMain"] {overflow:hidden!important}
[data-testid="stDialog"] [role="dialog"] {background:#111c2d;color:#e2e8f0}
</style>"""


def add_map_ui(m, df, warnings=None, error=None, auto_update=False):
    """UI and search share the renderer's validated, actually loaded observations."""
    esc = lambda value: escape(str(value), quote=True)
    data = m.weather_data
    observations = m.weather_frame
    summary = []
    for field, title, operation in [("temp", "最高溫", "idxmax"), ("temp", "最低溫", "idxmin"), ("precip", "最大雨量", "idxmax")]:
        values = observations[field].dropna()
        if values.empty:
            continue
        row = observations.loc[getattr(values, operation)()]
        place = " · ".join(filter(None, [row["countyName"], row["townName"], row["stationName"]]))
        unit = data["layers"][field]["unit"]
        summary.append(f'<div class="summary-reading"><span>{title}</span><b>{row[field]:.1f}<small> {unit}</small></b><small class="summary-place">{esc(place)}</small></div>')
    other_stats = []
    for field, title in [("temp", "平均溫"), ("wind", "最大風速")]:
        values = observations[field].dropna()
        if not values.empty:
            value = values.mean() if field == "temp" else values.max()
            place = "" if field == "temp" else " · " + observations.loc[values.idxmax(), "stationName"]
            other_stats.append(f'<p>{title} {value:.1f} {esc(data["layers"][field]["unit"])}{esc(place)}</p>')
    other_html = '<details><summary>其他統計</summary>' + ''.join(other_stats) + '</details>' if other_stats else ''
    times = [str(item["obsTime"]) for item in data["stations"] if item["obsTime"]]
    observed_at = max(times) if times else "尚無觀測資料"
    if warnings is None:
        warning_html = '<p>特報尚未取得，請至資料與設定同步。</p>'
    elif not warnings:
        warning_html = '<p>目前取得的特報：0 則</p>'
    else:
        warning_html = ''.join('<article class="weather-warning"><b>'+esc(w.get("title", "天氣特報"))+'</b><p>'+esc(w.get("description", ""))+'</p><small>'+esc(w.get("startTime", ""))+' ～ '+esc(w.get("endTime", ""))+'</small></article>' for w in warnings)
    options = ''.join(f'<option value="{key}">{esc(spec["title"])} · {esc(spec["unit"])}</option>' for key, spec in data["layers"].items())
    overlay_html = '<label class="weather-check"><input id="overlay-stations" type="checkbox"> 測站位置</label>' if data["stations"] else ''
    for kind, title in [("county", "縣市界線"), ("district", "行政區界線")]:
        if kind in data["boundaries"]:
            overlay_html += f'<label class="weather-check"><input id="overlay-{kind}" type="checkbox"> {title}</label>'
    state = "CWA 最新儲存觀測" if data["stations"] else "尚無 CWA 觀測資料，請同步資料"
    panels = {
        "topLeft": f'''<details open class="weather-glass weather-controls"><summary class="weather-heading"><span class="weather-eyebrow">TAIWAN WEATHER MAP</span><h1>台灣即時氣象</h1></summary><div class="controls-body"><p class="weather-status">{esc(state)}</p>
          <label for="weather-layer">主要氣象圖層</label><select id="weather-layer" {'disabled' if not options else ''}>{options or '<option>目前無可用氣象資料</option>'}</select>
          <div class="weather-overlays"><span class="control-label">疊加圖層</span>{overlay_html}</div>
          <details class="weather-options"><summary>地圖選項</summary><label for="weather-theme">底圖</label><select id="weather-theme"><option value="dark">深色</option><option value="street">街道</option></select><label class="weather-check"><input id="weather-labels" type="checkbox" checked> 顯示數值標籤</label><p>測站位置可獨立疊加；低縮放顯示縣市；中、高縮放皆顯示行政區，測站為資料來源。</p></details>
          <p class="weather-error">{esc(error) if error else ''}</p></div></details>''',
        "topRight": f'''<details open class="weather-glass weather-summary"><summary>☰ <span>即時概況</span><span class="weather-count">{len(data['stations'])} 站</span></summary><div class="weather-summary-body">{''.join(summary) or '<p>尚無有效氣象觀測</p>'}<p class="summary-time">最新觀測<br><time>{esc(observed_at)}</time><br>{'自動同步已啟用' if auto_update else '手動同步'}</p><p>各站最新觀測，非全日極值。</p>{other_html}<details><summary>天氣特報 · {len(warnings) if warnings is not None else '未取得'}</summary>{warning_html}</details></div></details>''',
        "bottomLeft": '<section class="weather-glass weather-legend" aria-label="氣象色階" aria-live="polite" hidden></section>',
    }
    search = '<div class="weather-glass weather-search"><label class="sr-only" for="weather-search">搜尋縣市、行政區（亦可查測站）</label><div class="search-input-row"><span aria-hidden="true">⌕</span><input id="weather-search" role="combobox" aria-autocomplete="list" aria-controls="weather-results" aria-expanded="false" placeholder="搜尋縣市、行政區（亦可查測站）" autocomplete="off"><button id="search-clear" aria-label="清除搜尋">×</button></div><div id="weather-results" role="listbox" hidden></div><div id="search-status" class="sr-only" role="status"></div></div>'
    config = safe_json({"panels":panels,"search":search})
    m.get_root().header.add_child(folium.Element('<style>'+ (ASSETS / "weather-map.css").read_text(encoding="utf-8") +'</style>'))
    script = (ASSETS / "weather-map.js").read_text(encoding="utf-8").replace("__WEATHER_MAP__", m.get_name()).replace("__WEATHER_CONFIG__", config)
    overlay = MacroElement()
    overlay.script = script
    overlay._template = Template("{% macro script(this, kwargs) %}{{ this.script }}{% endmacro %}")
    m.add_child(overlay)
