"""台灣氣象 Folium 地圖：沿用縣市 → 行政區縮放邏輯，高縮放仍維持行政區。

不同氣象指標共用分層與可視範圍 renderer；只聚合有值的 CWA 測站。
GeoJSON 僅用於界線、搜尋與觀測平均值著色，不產生虛構天氣資料。
"""

from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from spatial_mapping import DistrictIndex, assign_station_districts
from branca.element import MacroElement, Template
from typing import Any, Dict, List, Optional, Tuple
import folium
from html import escape
import pandas as pd

# ==============================================================================
# 可設定縮放閾值（Configurable Zoom Thresholds）
# ==============================================================================
COUNTY_ZOOM_THRESHOLD: int = 8
DISTRICT_ZOOM_THRESHOLD: int = 10

# 地圖初始中心與縮放
TAIWAN_CENTER: Tuple[float, float] = (23.75, 120.95)
TAIWAN_DEFAULT_ZOOM: float = 7.5
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
    """根據氣溫數值平滑映射對應顏色碼 (符合專業氣象色階)."""
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
    value_column: str = "temp",
) -> List[Dict[str, Any]]:
    """計算每個縣市的平均氣溫，返回縣市標記資料列表."""
    markers = []
    if df_stations.empty:
        return markers

    county_stats = (
        df_stations.groupby("countyName")[value_column]
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
    value_column: str = "temp",
) -> Dict[str, List[Dict[str, Any]]]:
    """計算每個縣市各鄉鎮區的平均氣溫，返回按縣市分組的標記資料."""
    result: Dict[str, List[Dict[str, Any]]] = {}
    if df_stations.empty:
        return result

    valid = df_stations[
        df_stations["townName"].notnull()
        & df_stations["lat"].notnull()
        & df_stations["lon"].notnull()
        & df_stations[value_column].notnull()
    ].copy()
    valid["townName"] = valid["townName"].astype(str).str.strip()
    valid = valid[valid["townName"].str.len() > 0]

    if valid.empty:
        return result

    grouped = (
        valid.groupby(["countyName", "townName"])
        .agg(
            avg_temp=(value_column, "mean"),
            avg_lat=("lat", "mean"),
            avg_lon=("lon", "mean"),
            station_count=(value_column, "count"),
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
    short_name = escape(county[:3] if len(county) > 3 else county)
    return (
        f'<div style="background:{color};color:#fff;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'微軟正黑體\',sans-serif;'
        f'font-size:12px;font-weight:800;padding:4px 6px 3px 6px;border-radius:16px;'
        f'border:2px solid rgba(255,255,255,0.7);'
        f'box-shadow:0 3px 14px rgba(0,0,0,0.6),0 1px 4px rgba(0,0,0,0.4);'
        f'text-align:center;white-space:nowrap;line-height:1.25;min-width:48px;">'
        f'<span style="font-size:11px;opacity:0.92;">{short_name}</span><br>'
        f'<span style="font-size:12px;letter-spacing:-0.5px;">🌡 {temp_str}</span></div>'
    )


def _district_marker_html(district: str, avg_temp: float) -> str:
    """產生鄉鎮區層級氣溫標記 HTML（小型圓角卡片）."""
    color = get_temperature_color(avg_temp)
    temp_str = f"{avg_temp:.1f}°C"
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


# Color breaks are shared by the markers, polygons and dynamic legend.
WEATHER_LAYERS = {
    "temp": {"title": "氣溫", "unit": "°C", "breaks": [5,10,15,20,24,27,30,33], "colors": ["#2563eb","#0284c7","#06b6d4","#0d9488","#10b981","#84cc16","#eab308","#f97316","#ef4444"]},
    "humid": {"title": "濕度", "unit": "%", "breaks": [20,40,60,80,90], "colors": ["#a16207","#d4a72c","#84cc16","#14b8a6","#0ea5e9","#6366f1"]},
    "precip": {"title": "雨量", "unit": "mm", "breaks": [0.1,1,5,10,20,50,100], "colors": ["#64748b","#38bdf8","#0ea5e9","#14b8a6","#84cc16","#facc15","#f97316","#db2777"]},
    "wind": {"title": "風速", "unit": "m/s", "breaks": [1,3,5,8,12,17,25], "colors": ["#64748b","#38bdf8","#14b8a6","#84cc16","#facc15","#f97316","#ef4444","#a855f7"]},
}


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")


def prepare_map_observations(df):
    """Validate display values without imputing any missing weather observations."""
    result = df.copy()
    for key in ("stationId", "stationName", "countyName", "townName", "weather", "obsTime"):
        result[key] = result.get(key, pd.Series(index=result.index, dtype=str)).fillna("").astype(str)
    for key in ("lat", "lon", "temp", "humid", "precip", "wind", "dailyHigh", "dailyLow"):
        values = pd.to_numeric(result.get(key, pd.Series(index=result.index, dtype=float)), errors="coerce")
        result[key] = values.replace([float("inf"), -float("inf"), -99, -999], float("nan"))
    result["temp"] = result["temp"].where(result["temp"].between(-50,60))
    result["humid"] = result["humid"].where(result["humid"].between(0,100))
    for field in ("precip", "wind"):
        result[field] = result[field].where(result[field] >= 0)
    return result[result["lat"].between(-90,90) & result["lon"].between(-180,180)].reset_index(drop=True)


@lru_cache(maxsize=4)
def _load_boundaries_cached(versions):
    boundaries = {}
    for kind, filename, _ in versions:
        boundaries[kind] = json.loads(Path(filename).read_text(encoding="utf-8"))
    return boundaries, DistrictIndex(boundaries.get("district", {}))


def load_boundaries():
    versions = []
    for kind, filename in [("county", "counties.geojson"), ("district", "towns.geojson")]:
        path = Path(__file__).parent / "assets" / filename
        if path.exists():
            versions.append((kind, str(path), path.stat().st_mtime_ns))
    return _load_boundaries_cached(tuple(versions))


def build_weather_payload(df, boundaries, district_index):
    layers = {key: spec for key, spec in WEATHER_LAYERS.items() if df[key].notna().any()}
    stations = json.loads(df.to_json(orient="records", force_ascii=False))
    for index, item in enumerate(stations):
        item.update(id="station:" + (item["stationId"] or str(index)), kind="station", name=item["stationName"], county=item["countyName"], district=item["townName"])
    regions = {"county": {}, "district": {}}
    for kind in regions:
        for station in stations:
            if not station["county"] or (kind == "district" and not station["district"]):
                continue
            key = (station["county"], station["district"] if kind == "district" else "")
            region = regions[kind].setdefault(key, {"station_ids": [], "values": {}, "counts": {}, "points": []})
            region["station_ids"].append(station["id"])
            region["points"].append((station["lat"],station["lon"]))
    datasets = {}
    for key in layers:
        counties = _build_county_markers(df, key)
        districts = [item for items in _build_district_markers(df, key).values() for item in items]
        for kind, items in [("county", counties), ("district", districts)]:
            for item in items:
                item["value"] = item.pop("avg_temp")
                item["kind"] = kind
                item["name"] = item.get("district", item["county"])
                item["id"] = kind + ":" + item["county"] + ":" + item.get("district", "")
                region = regions[kind][(item["county"], item.get("district", ""))]
                region["values"][key] = item["value"]
                region["counts"][key] = item["station_count"]
        datasets[key] = {"county": counties, "district": districts}
    # Stable anchors across metrics: prefer a source inside the polygon.
    # Offshore CWA fallback sources use an interior geometry label point.
    for dataset in datasets.values():
        for kind, items in dataset.items():
            for item in items:
                region = regions[kind][(item["county"], item.get("district", ""))]
                item.update({key:region[key] for key in ("station_ids", "values", "counts")})
                if kind == "district":
                    pair = (item["county"], item["district"])
                    points = [point for point in region["points"] if pair in district_index.candidates(point[1],point[0])]
                    if not points:
                        anchor = district_index.label_point(*pair)
                        if anchor:
                            item["lat"], item["lon"] = anchor
                        continue
                    lat, lon = (sum(p[i] for p in points)/len(points) for i in (0,1))
                    item["lat"], item["lon"] = min(points, key=lambda p:(p[0]-lat)**2+(p[1]-lon)**2)
    return {"layers": layers, "datasets": datasets, "stations": stations, "boundaries": boundaries}


def create_taiwan_realtime_weather_map(
    df_stations: pd.DataFrame,
    map_theme: str = "dark",
    show_labels: bool = True,
    density_mode: str = "all",
    focus_county: Optional[str] = None,
) -> folium.Map:
    """建立按縮放層級切換的縣市／行政區氣象地圖，測站保留為來源。"""
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
        # CARTO's current basemap endpoints require an API key. Keep the map
        # usable without an external key; OSM is also used for street mode.
        tile_name = "OpenStreetMap"
        tile_attr = None

    m = folium.Map(
        location=center,
        zoom_start=zoom_start,
        tiles=tile_name,
        attr=tile_attr,
        control_scale=True,
        prefer_canvas=True,
        zoom_control=False,
        zoom_snap=0.5,
    )

    # One renderer and one zoom handler serve every weather variable.
    df = prepare_map_observations(df_stations)
    boundaries, district_index = load_boundaries()
    df = assign_station_districts(df, district_index)
    payload = build_weather_payload(df, boundaries, district_index)
    payload["thresholds"] = {"county": COUNTY_ZOOM_THRESHOLD, "district": DISTRICT_ZOOM_THRESHOLD}
    payload["initial"] = {"theme": map_theme, "labels": show_labels}
    m.weather_data = payload
    m.weather_frame = df
    script = (Path(__file__).parent / "assets" / "weather-renderer.js").read_text(encoding="utf-8")
    script = script.replace("__WEATHER_MAP__", m.get_name()).replace("__WEATHER_DATA__", safe_json(payload))
    runtime = MacroElement()
    runtime.script = script
    runtime._template = Template("{% macro script(this, kwargs) %}{{ this.script }}{% endmacro %}")
    m.add_child(runtime)
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
