"""台灣氣溫地理地圖視覺化模組 — 階層式縮放地圖.

使用 Folium 繪製現代化深色台灣即時氣溫地圖，支援：
- 縮小時顯示縣市平均氣溫標記
- 放大時自動切換顯示該縣市各行政區（鄉鎮區）個別氣溫標記
- 基於真實 CWA O-A0003-001 測站資料，不虛構任何氣溫

架構說明（Hierarchical Zoom Logic）：
  zoom <= COUNTY_ZOOM_THRESHOLD     → 顯示縣市層級（縣市可用測站平均氣溫）
  zoom > COUNTY_ZOOM_THRESHOLD      → 顯示目前視窗附近、具有真實測站資料的行政區氣溫
  不再顯示 360+ 個個別測站，地圖維持兩層清楚的視覺階層。

資料說明：
  CWA O-A0003-001 提供全台 360+ 自動氣象測站，每站均有 countyName（縣市）、
  townName（鄉鎮區）、lat/lon、temp 等欄位。
  - 縣市層：對同一縣市所有測站氣溫取平均 → county-level marker
  - 鄉鎮區層：對同一縣市同一鄉鎮區的測站氣溫取平均 → district-level marker
  此為真實資料，非虛構。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
import folium
from folium.plugins import Fullscreen
import pandas as pd

# ==============================================================================
# 可設定縮放閾值（Configurable Zoom Thresholds）
# ==============================================================================
# zoom <= COUNTY_ZOOM_THRESHOLD → 顯示縣市層
# zoom > COUNTY_ZOOM_THRESHOLD  → 顯示行政區層
COUNTY_ZOOM_THRESHOLD: int = 8

# 地圖初始中心與縮放
TAIWAN_CENTER: Tuple[float, float] = (23.75, 120.95)
TAIWAN_DEFAULT_ZOOM: int = 7
COUNTY_FOCUS_ZOOM: int = 10

# 台灣主要氣象分區與各縣市代表經緯度 (Latitude, Longitude)
REGION_COORDINATES: Dict[str, Tuple[float, float]] = {
    "北部地區": (25.04, 121.55),
    "中部地區": (24.15, 120.67),
    "南部地區": (22.63, 120.30),
    "東部地區": (23.98, 121.60),
    "東北部地區": (24.75, 121.75),
    "東南部地區": (22.75, 121.15),
    "澎湖": (23.57, 119.58),
    "澎湖地區": (23.57, 119.58),
    "金門": (24.44, 118.37),
    "金門地區": (24.44, 118.37),
    "馬祖": (26.15, 119.94),
    "馬祖地區": (26.15, 119.94),
    "臺北市": (25.0375, 121.5637),
    "新北市": (25.0124, 121.4657),
    "基隆市": (25.1276, 121.7392),
    "桃園市": (24.9936, 121.3010),
    "新竹市": (24.8138, 120.9675),
    "新竹縣": (24.8387, 121.0177),
    "苗栗縣": (24.5602, 120.8214),
    "臺中市": (24.1477, 120.6736),
    "彰化縣": (24.0518, 120.5161),
    "南投縣": (23.9610, 120.9719),
    "雲林縣": (23.7092, 120.4313),
    "嘉義市": (23.4801, 120.4491),
    "嘉義縣": (23.4518, 120.2555),
    "臺南市": (22.9997, 120.2270),
    "高雄市": (22.6273, 120.3014),
    "屏東縣": (22.5519, 120.5487),
    "宜蘭縣": (24.7021, 121.7377),
    "花蓮縣": (23.9872, 121.6016),
    "臺東縣": (22.7583, 121.1444),
    "澎湖縣": (23.5712, 119.5793),
    "金門縣": (24.4492, 118.3766),
    "連江縣": (26.1505, 119.9499),
}


def get_temperature_color(temp: Optional[float]) -> str:
    """根據氣溫數值平滑映射對應顏色碼 (符合專業氣象色階).

    < 5°C: 深藍 (#2563eb)
    5~10°C: 天藍 (#0284c7)
    10~15°C: 湖水藍 (#06b6d4)
    15~20°C: 藍綠 (#0d9488)
    20~24°C: 翠綠 (#10b981)
    24~27°C: 黃綠 (#84cc16)
    27~30°C: 溫暖金黃 (#eab308)
    30~33°C: 亮橙 (#f97316)
    >= 33°C: 烈紅 (#ef4444)
    """
    if temp is None or pd.isna(temp):
        return "#64748b"  # 灰藍
    
    t = float(temp)
    if t < 5.0:
        return "#2563eb"
    elif t < 10.0:
        return "#0284c7"
    elif t < 15.0:
        return "#06b6d4"
    elif t < 20.0:
        return "#0d9488"
    elif t < 24.0:
        return "#10b981"
    elif t < 27.0:
        return "#84cc16"
    elif t < 30.0:
        return "#eab308"
    elif t < 33.0:
        return "#f97316"
    else:
        return "#ef4444"


def _build_county_markers(
    df_stations: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """計算每個縣市的平均氣溫，返回縣市標記資料列表.

    Returns:
        List of dicts with keys: county, lat, lon, avg_temp, station_count
    """
    markers = []
    if df_stations.empty:
        return markers

    county_stats = (
        df_stations.groupby("countyName")["temp"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "avg_temp", "count": "station_count"})
    )

    for _, row in county_stats.iterrows():
        county = str(row["countyName"]).strip()
        avg_temp = row["avg_temp"]
        station_count = int(row["station_count"])
        if county not in REGION_COORDINATES:
            continue
        if pd.isna(avg_temp):
            continue
        lat, lon = REGION_COORDINATES[county]
        markers.append({
            "county": county,
            "lat": lat,
            "lon": lon,
            "avg_temp": float(avg_temp),
            "station_count": station_count,
        })
    return markers


def _build_district_markers(
    df_stations: pd.DataFrame,
) -> Dict[str, List[Dict[str, Any]]]:
    """計算每個縣市各鄉鎮區的平均氣溫，返回按縣市分組的標記資料.

    資料來源：CWA O-A0003-001 每個測站均有 townName 欄位及真實 lat/lon。
    對同一縣市、同一鄉鎮區的多個測站取平均氣溫與平均座標。
    此為真實資料，非虛構。

    Returns:
        Dict mapping countyName → list of district marker dicts.
        每個 dict 包含: county, district, lat, lon, avg_temp, station_count
    """
    result: Dict[str, List[Dict[str, Any]]] = {}
    if df_stations.empty:
        return result

    valid = df_stations[
        df_stations["townName"].notnull()
        & df_stations["lat"].notnull()
        & df_stations["lon"].notnull()
        & df_stations["temp"].notnull()
    ].copy()
    valid["townName"] = valid["townName"].astype(str).str.strip()
    valid = valid[valid["townName"].str.len() > 0]

    if valid.empty:
        return result

    grouped = (
        valid.groupby(["countyName", "townName"])
        .agg(
            avg_temp=("temp", "mean"),
            avg_lat=("lat", "mean"),
            avg_lon=("lon", "mean"),
            station_count=("temp", "count"),
        )
        .reset_index()
    )

    for _, row in grouped.iterrows():
        county = str(row["countyName"]).strip()
        district = str(row["townName"]).strip()
        avg_temp = row["avg_temp"]
        avg_lat = row["avg_lat"]
        avg_lon = row["avg_lon"]
        station_count = int(row["station_count"])
        if pd.isna(avg_temp) or pd.isna(avg_lat) or pd.isna(avg_lon):
            continue
        if county not in result:
            result[county] = []
        result[county].append({
            "county": county,
            "district": district,
            "lat": float(avg_lat),
            "lon": float(avg_lon),
            "avg_temp": float(avg_temp),
            "station_count": station_count,
        })
    return result


def _county_marker_html(county: str, avg_temp: float, station_count: int) -> str:
    """產生縣市層級氣溫標記 HTML（大型圓角卡片）."""
    color = get_temperature_color(avg_temp)
    temp_str = f"{avg_temp:.1f}°C"
    short_name = county[:3] if len(county) > 3 else county
    return (
        f'<div style="background:{color};color:#fff;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'微軟正黑體\',sans-serif;'
        f'font-size:12px;font-weight:800;padding:5px 10px 4px 10px;border-radius:20px;'
        f'border:2px solid rgba(255,255,255,0.7);'
        f'box-shadow:0 3px 14px rgba(0,0,0,0.6),0 1px 4px rgba(0,0,0,0.4);'
        f'text-align:center;white-space:nowrap;line-height:1.25;min-width:60px;">'
        f'<span style="font-size:11px;opacity:0.92;">{short_name}</span><br>'
        f'<span style="font-size:14px;letter-spacing:-0.5px;">🌡 {temp_str}</span></div>'
    )


def _district_marker_html(district: str, avg_temp: float) -> str:
    """產生鄉鎮區層級氣溫標記 HTML（小型圓角卡片）."""
    color = get_temperature_color(avg_temp)
    temp_str = f"{avg_temp:.1f}°C"
    # 去末尾行政區後綴以縮短，保留可讀性
    short = district.rstrip("區鄉鎮市") if len(district) > 2 else district
    return (
        f'<div style="background:linear-gradient(135deg,{color}dd,{color}aa);color:#fff;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'微軟正黑體\',sans-serif;'
        f'font-size:11px;font-weight:700;padding:4px 9px 3px 9px;border-radius:14px;'
        f'border:1.5px solid rgba(255,255,255,0.65);box-shadow:0 2px 8px rgba(0,0,0,0.55);'
        f'text-align:center;white-space:nowrap;line-height:1.3;min-width:50px;">'
        f'<span style="font-size:10px;opacity:0.9;">{short}</span><br>'
        f'<span style="font-size:13px;">{temp_str}</span></div>'
    )


def create_taiwan_realtime_weather_map(
    df_stations: pd.DataFrame,
    map_theme: str = "dark",
    show_labels: bool = True,
    density_mode: str = "all",
    focus_county: Optional[str] = None,
) -> folium.Map:
    """建立兩層式台灣即時氣溫地圖。

    互動邏輯：
      - Zoomed out：顯示縣市平均氣溫。
      - Zoom in：隱藏縣市標記，改顯示目前地圖視窗內、具有真實 CWA 測站資料的行政區氣溫。
      - Zoom in/out 不重新呼叫 API，也不顯示 360+ 個個別測站。

    行政區溫度來自 CWA O-A0003-001 真實測站資料：同一縣市＋行政區的
    可用測站取平均。沒有測站資料的行政區不會被虛構出溫度。
    """
    center = list(TAIWAN_CENTER)
    zoom_start = TAIWAN_DEFAULT_ZOOM

    if focus_county and focus_county in REGION_COORDINATES:
        coords = REGION_COORDINATES[focus_county]
        center = [coords[0], coords[1]]
        zoom_start = COUNTY_FOCUS_ZOOM

    if map_theme == "street":
        tile_name = "OpenStreetMap"
        tile_attr = None
    else:
        tile_name = "CartoDB dark_matter"
        tile_attr = '&copy; <a href="https://carto.com/">CARTO</a>'

    m = folium.Map(
        location=center,
        zoom_start=zoom_start,
        tiles=tile_name,
        attr=tile_attr,
        control_scale=True,
        prefer_canvas=True,
    )

    Fullscreen(
        position="topright",
        title="全螢幕檢視",
        title_cancel="結束全螢幕",
        force_separate_button=True,
    ).add_to(m)

    # 使用者提示：讓「縮小看縣市、放大看行政區」的互動方式一眼可懂。
    instruction_html = """
    <div style="
        position: fixed;
        top: 12px;
        left: 55px;
        z-index: 9999;
        background: rgba(15,23,42,0.90);
        color: white;
        padding: 8px 12px;
        border-radius: 10px;
        font-family: -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft JhengHei',sans-serif;
        font-size: 12px;
        line-height: 1.45;
        box-shadow: 0 3px 12px rgba(0,0,0,.35);
        border: 1px solid rgba(255,255,255,.15);
    ">
      <b>🌡️ 即時氣溫地圖</b><br>
      🔍 縮小 → 縣市氣溫　　🔎 放大 → 行政區氣溫
    </div>
    """
    m.get_root().html.add_child(folium.Element(instruction_html))

    # ================================================================
    # Layer 1：縣市平均氣溫
    # ================================================================
    county_group = folium.FeatureGroup(name="縣市氣溫", show=True)
    county_markers = _build_county_markers(df_stations)

    for mk in county_markers:
        county = mk["county"]
        lat = mk["lat"]
        lon = mk["lon"]
        avg_temp = mk["avg_temp"]
        station_count = mk["station_count"]
        color = get_temperature_color(avg_temp)

        icon_html = _county_marker_html(county, avg_temp, station_count)
        popup_html = (
            f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;min-width:170px;'>"
            f"<b style='font-size:15px;'>{county}</b><br>"
            f"<div style='text-align:center;margin:8px 0;padding:8px;background:#f8fafc;border-radius:8px;'>"
            f"<span style='font-size:24px;font-weight:800;color:{color};'>{avg_temp:.1f}°C</span><br>"
            f"<span style='font-size:11px;color:#64748b;'>縣市可用測站平均（{station_count} 站）</span>"
            f"</div>"
            f"<div style='font-size:11px;color:#64748b;'>🔎 放大地圖後可查看行政區氣溫</div>"
            f"</div>"
        )
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(icon_size=(90, 54), icon_anchor=(45, 27), html=icon_html),
            popup=folium.Popup(popup_html, max_width=230),
            tooltip=f"{county}：{avg_temp:.1f}°C（{station_count} 站平均）",
        ).add_to(county_group)

    county_group.add_to(m)

    # ================================================================
    # Layer 2：行政區平均氣溫
    #
    # 重要設計：
    # 不使用 FeatureGroup 做行政區切換，而是直接保留每一個
    # Leaflet Marker 的 JavaScript reference。
    #
    # 這樣可以在 zoom > 8 時，依「目前地圖視窗」逐一決定哪些
    # 行政區標記要顯示。放大到台中，就只顯示目前視窗內的台中
    # 行政區；移到其他縣市也會同步更新。
    # ================================================================
    district_markers_by_county = _build_district_markers(df_stations)
    district_marker_refs: List[Dict[str, Any]] = []

    # 所有行政區 Marker 先放在一個 Python/Folium 容器中，
    # 但這個容器本身不加入地圖；避免頁面初始就顯示全部行政區。
    # JavaScript 之後直接控制每一個 Leaflet Marker。
    district_group = folium.FeatureGroup(
        name="行政區氣溫",
        show=False,
        overlay=True,
        control=False,
    )

    for county, district_list in district_markers_by_county.items():
        for dk in district_list:
            district = dk["district"]
            d_lat = dk["lat"]
            d_lon = dk["lon"]
            d_temp = dk["avg_temp"]
            d_count = dk["station_count"]
            d_color = get_temperature_color(d_temp)

            # 直接把「行政區 + 氣溫」放在地圖座標上，
            # 不要求使用者點擊 Popup 才看到。
            icon_html = _district_marker_html(district, d_temp)
            popup_html = (
                f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;min-width:165px;'>"
                f"<b style='font-size:14px;'>{district}</b>"
                f"<span style='font-size:10px;color:#94a3b8;margin-left:6px;'>{county}</span><br>"
                f"<div style='text-align:center;margin:8px 0;padding:8px;background:#f8fafc;border-radius:8px;'>"
                f"<span style='font-size:22px;font-weight:800;color:{d_color};'>{d_temp:.1f}°C</span><br>"
                f"<span style='font-size:11px;color:#64748b;'>可用測站平均（{d_count} 站）</span>"
                f"</div></div>"
            )

            marker = folium.Marker(
                location=[d_lat, d_lon],
                icon=folium.DivIcon(
                    icon_size=(92, 52),
                    icon_anchor=(46, 26),
                    html=icon_html,
                ),
                popup=folium.Popup(popup_html, max_width=210),
                tooltip=f"{district}（{county}）：{d_temp:.1f}°C",
            )

            # 加入「預設隱藏」的行政區 FeatureGroup，而不是直接加入地圖。
            # 這樣初始 zoom=7 時，瀏覽器根本不會繪製行政區 Marker。
            marker.add_to(district_group)

            district_marker_refs.append({
                "county": county,
                "district": district,
                "lat": float(d_lat),
                "lon": float(d_lon),
                "markerName": marker.get_name(),
            })

    # 注意：這個 FeatureGroup 只作為 Python/Folium 的容器，
    # 不把它加入地圖。否則在 zoom > 8 時重新加入 FeatureGroup
    # 會一次把所有行政區 Marker 帶回來，破壞「只顯示目前視窗」
    # 的邏輯。JavaScript 會直接控制每一個 Marker。

    # ================================================================
    # JavaScript：兩層切換
    #
    # Level 1：zoom <= 8
    #   顯示縣市平均氣溫，隱藏所有行政區。
    #
    # Level 2：zoom > 8
    #   隱藏縣市，依目前地圖 bounds 顯示行政區氣溫。
    #
    # 注意：行政區不是用「縣市中心點」判斷，而是用「每一個
    # 行政區 marker 的真實座標」判斷。因此放大到台中市中心、
    # 即使台中市的代表座標不在當前視窗中心，也不會導致行政區
    # 圖層整組消失。
    # ================================================================
    map_var = m.get_name()
    county_var = county_group.get_name()

    # IMPORTANT:
    # markerName is a Folium-generated JavaScript variable name.
    # Do NOT serialize it with json.dumps(), because that turns it into
    # a plain string such as "marker_xxxxx". Leaflet map.hasLayer()
    # and map.addLayer() require the actual Marker object.
    district_refs_js = json.dumps(
        [
            {
                "county": item["county"],
                "district": item["district"],
                "lat": item["lat"],
                "lon": item["lon"],
            }
            for item in district_marker_refs
        ],
        ensure_ascii=False,
    )

    # Inject the real JS Marker variable references after JSON generation.
    for item in district_marker_refs:
        district_refs_js = district_refs_js.replace(
            f'"district": {json.dumps(item["district"], ensure_ascii=False)}',
            f'"district": {json.dumps(item["district"], ensure_ascii=False)}, "marker": {item["markerName"]}',
            1,
        )

    toggle_js = f"""
<script>
(function() {{
    var COUNTY_THRESHOLD = {COUNTY_ZOOM_THRESHOLD};

    function waitForMap() {{
        if (typeof {map_var} === 'undefined') {{
            setTimeout(waitForMap, 150);
            return;
        }}

        var mapObj = {map_var};
        var countyLayer = {county_var};
        var districtMarkers = {district_refs_js};

        function markerInBounds(item) {{
            var bounds = mapObj.getBounds();

            // 只有當行政區的實際座標在目前視窗內才顯示。
            return bounds.contains([item.lat, item.lon]);
        }}

        function hideAllDistrictMarkers() {{
            districtMarkers.forEach(function(item) {{
                var marker = item.marker;
                if (marker && mapObj.hasLayer(marker)) {{
                    mapObj.removeLayer(marker);
                }}
            }});
        }}

        function showVisibleDistrictMarkers() {{
            districtMarkers.forEach(function(item) {{
                var marker = item.marker;

                if (!marker) return;

                if (markerInBounds(item)) {{
                    if (!mapObj.hasLayer(marker)) {{
                        mapObj.addLayer(marker);
                    }}
                }} else {{
                    if (mapObj.hasLayer(marker)) {{
                        mapObj.removeLayer(marker);
                    }}
                }}
            }});
        }}

        function updateWeatherLevel() {{
            var zoom = mapObj.getZoom();

            if (zoom <= COUNTY_THRESHOLD) {{
                // ================================
                // 縮小：縣市氣溫
                // ================================
                if (!mapObj.hasLayer(countyLayer)) {{
                    mapObj.addLayer(countyLayer);
                }}

                hideAllDistrictMarkers();
            }} else {{
                // ================================
                // 放大：行政區氣溫
                // ================================
                if (mapObj.hasLayer(countyLayer)) {{
                    mapObj.removeLayer(countyLayer);
                }}

                // 直接控制每一個行政區 Marker。
                // 不加入整個 FeatureGroup，避免一次顯示全部行政區。
                showVisibleDistrictMarkers();
            }}
        }}

        mapObj.on('zoomend', updateWeatherLevel);
        mapObj.on('moveend', updateWeatherLevel);

        // 初始化
        updateWeatherLevel();
    }}

    waitForMap();
}})();
</script>
"""

    m.get_root().html.add_child(folium.Element(toggle_js))
    return m


def create_taiwan_weather_map(
    df: pd.DataFrame,
    selected_date: str,
    selected_region: Optional[str] = None,
) -> folium.Map:
    """相容舊版預報資料地圖渲染函式."""
    taiwan_center = [23.7, 120.95]
    m = folium.Map(
        location=taiwan_center,
        zoom_start=7,
        tiles="CartoDB dark_matter",
        control_scale=True,
    )

    if df.empty:
        return m

    df_date = df[df["dataDate"] == selected_date]

    for _, row in df_date.iterrows():
        region_name = str(row.get("regionName", "")).strip()
        coords = REGION_COORDINATES.get(region_name)

        if not coords:
            for k, v in REGION_COORDINATES.items():
                if k in region_name or region_name in k:
                    coords = v
                    break

        if not coords:
            continue

        min_t = row.get("minT")
        max_t = row.get("maxT")
        avg_t = (float(min_t) + float(max_t)) / 2.0 if (pd.notnull(min_t) and pd.notnull(max_t)) else None

        color = get_temperature_color(avg_t)
        temp_str = f"{avg_t:.0f}°" if avg_t is not None else "--"

        badge_html = f"""
        <div style="
            background: {color};
            color: #ffffff;
            font-size: 13px;
            font-weight: 800;
            padding: 3px 9px;
            border-radius: 14px;
            border: 1.5px solid rgba(255, 255, 255, 0.6);
            box-shadow: 0 3px 6px rgba(0,0,0,0.5);
            text-align: center;
            display: inline-block;
        ">
            {temp_str}
        </div>
        """

        folium.Marker(
            location=coords,
            icon=folium.DivIcon(icon_size=(38, 24), icon_anchor=(19, 12), html=badge_html),
            tooltip=f"{region_name}: {avg_t:.1f}°C" if avg_t is not None else region_name,
        ).add_to(m)

    return m

