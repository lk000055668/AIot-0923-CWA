"""天氣預報資料處理與 JSON 解析模組.

負責解析 CWA API 回傳的原始 JSON 資料，擷取地區、日期、MinT 與 MaxT，
處理缺失值與型態轉換，並輸出結構化的 Pandas DataFrame。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import math
import pandas as pd
from region_names import normalizeCountyName, normalizeDistrictName


class DataProcessingError(Exception):
    """資料處理與解析自訂例外."""
    pass


def _extract_element_value(item: Dict[str, Any]) -> Optional[float]:
    """從天氣要素時間區間中提取數值 (相容 elementValue 與 parameter 格式)."""
    # 情況 1: elementValue 為 list of dict (如 F-C0032-005, F-D0047 系列)
    if "elementValue" in item and isinstance(item["elementValue"], list):
        for val_dict in item["elementValue"]:
            if isinstance(val_dict, dict) and "value" in val_dict:
                try:
                    val_str = str(val_dict["value"]).strip()
                    if val_str and val_str not in ("-", "None", "null"):
                        return float(val_str)
                except (ValueError, TypeError):
                    continue

    # 情況 2: parameter 格式 (如 F-C0032-001)
    if "parameter" in item and isinstance(item["parameter"], dict):
        param = item["parameter"]
        val_name = param.get("parameterName")
        if val_name is not None:
            try:
                val_str = str(val_name).strip()
                if val_str and val_str not in ("-", "None", "null"):
                    return float(val_str)
            except (ValueError, TypeError):
                pass

    return None


def _extract_date_str(time_dict: Dict[str, Any]) -> Optional[str]:
    """從時間物件中解析出 YYYY-MM-DD 格式日期字串."""
    # 優先嘗試 startTime 或 dataTime 或 time
    for key in ("startTime", "dataTime", "time", "endTime"):
        if key in time_dict and isinstance(time_dict[key], str):
            raw_time = time_dict[key].strip()
            if len(raw_time) >= 10:
                # 取得 YYYY-MM-DD 部分
                date_part = raw_time[:10]
                # 簡單驗證是否符合 YYYY-MM-DD 格式 (含兩個連字號)
                if date_part.count("-") == 2 or date_part.count("/") == 2:
                    return date_part.replace("/", "-")
    return None


def parse_weather_json(raw_json: Dict[str, Any]) -> pd.DataFrame:
    """解析 CWA 氣象 JSON 資料為結構化 DataFrame.

    欄位包含: regionName, dataDate, minT, maxT

    Args:
        raw_json: CWA API 回傳的原始字典資料。

    Returns:
        pd.DataFrame: 整理後的氣溫預報資料表。

    Raises:
        DataProcessingError: JSON 結構不符合預期或無有效資料時拋出。
    """
    if not isinstance(raw_json, dict):
        raise DataProcessingError("傳入的資料必須為字典型態 (dict)。")

    records = raw_json.get("records")
    if not records or not isinstance(records, dict):
        raise DataProcessingError("JSON 缺少 'records' 區塊或格式不正確。")

    # 定位 location 清單 (支援 records.locations[0].location 與 records.location)
    location_list: List[Dict[str, Any]] = []

    if "locations" in records and isinstance(records["locations"], list) and len(records["locations"]) > 0:
        for loc_group in records["locations"]:
            if isinstance(loc_group, dict) and "location" in loc_group and isinstance(loc_group["location"], list):
                location_list.extend(loc_group["location"])
    elif "location" in records and isinstance(records["location"], list):
        location_list.extend(records["location"])

    if not location_list:
        raise DataProcessingError("在 CWA records 中找不到任何 location 資料。")

    rows: List[Dict[str, Any]] = []

    for loc in location_list:
        if not isinstance(loc, dict):
            continue

        region_name = loc.get("locationName")
        if not region_name or not isinstance(region_name, str):
            continue

        weather_elements = loc.get("weatherElement", [])
        if not isinstance(weather_elements, list):
            continue

        # 整理該地區的 MinT 與 MaxT 時間序列
        # key: date_str (YYYY-MM-DD) -> {"minT": [...], "maxT": [...]}
        date_records: Dict[str, Dict[str, List[float]]] = {}

        for elem in weather_elements:
            if not isinstance(elem, dict):
                continue

            elem_name = str(elem.get("elementName", "")).strip()
            if elem_name not in ("MinT", "MaxT", "MinTemperature", "MaxTemperature"):
                continue

            time_slots = elem.get("time", [])
            if not isinstance(time_slots, list):
                continue

            is_min = elem_name in ("MinT", "MinTemperature")

            for slot in time_slots:
                if not isinstance(slot, dict):
                    continue

                date_str = _extract_date_str(slot)
                if not date_str:
                    continue

                temp_val = _extract_element_value(slot)
                if temp_val is None:
                    continue

                if date_str not in date_records:
                    date_records[date_str] = {"minT": [], "maxT": []}

                if is_min:
                    date_records[date_str]["minT"].append(temp_val)
                else:
                    date_records[date_str]["maxT"].append(temp_val)

        # 聚合每日氣溫：當天最低溫為 min(minT)，當天最高溫為 max(maxT)
        for date_str, temp_data in date_records.items():
            min_list = temp_data["minT"]
            max_list = temp_data["maxT"]

            final_min = min(min_list) if min_list else None
            final_max = max(max_list) if max_list else None

            # 若其中一者缺失，或 min > max 的異常防呆
            if final_min is not None and final_max is not None:
                if final_min > final_max:
                    final_min, final_max = final_max, final_min

            rows.append({
                "regionName": region_name.strip(),
                "dataDate": date_str,
                "minT": final_min,
                "maxT": final_max,
            })

    if not rows:
        raise DataProcessingError("未能自 JSON 提取出任何有效之氣溫預報紀錄。")

    df = pd.DataFrame(rows)
    return normalize_weather_data(df)


def normalize_weather_data(df: pd.DataFrame) -> pd.DataFrame:
    """清理與正規化氣溫資料表.

    - 確保欄位齊全且無多餘欄位
    - 轉換資料型別 (regionName: str, dataDate: str, minT: float, maxT: float)
    - 排除全為 NaN 之無效紀錄
    - 依照 regionName, dataDate 排序去重
    """
    required_cols = ["regionName", "dataDate", "minT", "maxT"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    df = df[required_cols].copy()

    # 清除前後空白與型態轉換
    df["regionName"] = df["regionName"].astype(str).str.strip()
    df["dataDate"] = df["dataDate"].astype(str).str.strip()
    df["minT"] = pd.to_numeric(df["minT"], errors="coerce")
    df["maxT"] = pd.to_numeric(df["maxT"], errors="coerce")

    # 移除 regionName 或 dataDate 為空者
    df = df[df["regionName"].str.len() > 0]
    df = df[df["dataDate"].str.len() >= 8]

    # 去重並保留每地區每日期之最新一筆
    df = df.drop_duplicates(subset=["regionName", "dataDate"], keep="last")

    # 依地區與日期排序
    df = df.sort_values(by=["regionName", "dataDate"]).reset_index(drop=True)

    return df


def parse_realtime_station_json(raw_json: Dict[str, Any]) -> pd.DataFrame:
    """解析 CWA 自動氣象站觀測資料 (O-A0003-001) 為測站氣象 DataFrame.

    欄位包含: stationId, stationName, countyName, townName, lat, lon, temp,
             dailyHigh, dailyLow, precip, wind, humid, weather, obsTime
    """
    if not isinstance(raw_json, dict):
        raise DataProcessingError("傳入的資料必須為字典型態 (dict)。")

    records = raw_json.get("records")
    if not records or not isinstance(records, dict):
        raise DataProcessingError("JSON 缺少 'records' 區塊或格式不正確。")

    stations = records.get("Station") or records.get("station") or records.get("location") or []
    if not stations or not isinstance(stations, list):
        raise DataProcessingError("在 CWA records 中找不到任何 Station 測站資料。")

    rows: List[Dict[str, Any]] = []

    for st in stations:
        if not isinstance(st, dict):
            continue

        st_id = st.get("StationId") or st.get("stationId") or ""
        st_name = st.get("StationName") or st.get("stationName") or st.get("locationName") or ""

        geo = st.get("GeoInfo") or st.get("geoInfo") or {}
        coords = geo.get("Coordinates", []) if isinstance(geo, dict) else []
        wgs84 = next((c for c in coords if isinstance(c, dict) and c.get("CoordinateName") == "WGS84"), coords[0] if coords and isinstance(coords[0], dict) else {})

        lat_val = wgs84.get("StationLatitude") or geo.get("StationLatitude") or st.get("lat")
        lon_val = wgs84.get("StationLongitude") or geo.get("StationLongitude") or st.get("lon")

        try:
            lat = float(lat_val) if lat_val is not None else None
            lon = float(lon_val) if lon_val is not None else None
        except (ValueError, TypeError):
            lat, lon = None, None

        county = geo.get("CountyName") or st.get("countyName") or ""
        town = geo.get("TownName") or st.get("townName") or ""

        we = st.get("WeatherElement") or st.get("weatherElement") or {}
        if not isinstance(we, dict):
            we = {}

        def observed_number(value, minimum=None, maximum=None):
            try:
                number = float(value)
            except (ValueError, TypeError):
                return None
            if not math.isfinite(number) or number in (-99, -999):
                return None
            if minimum is not None and number < minimum:
                return None
            if maximum is not None and number > maximum:
                return None
            return number

        # Preserve valid zeroes; never turn missing observations into zero.
        temp = observed_number(we.get("AirTemperature", we.get("airTemperature")), -50, 60)

        # 今日極端溫
        daily_high = None
        daily_low = None
        de = we.get("DailyExtreme") or {}
        if isinstance(de, dict):
            dh = de.get("DailyHigh", {}).get("TemperatureInfo", {}).get("AirTemperature") if isinstance(de.get("DailyHigh"), dict) else None
            dl = de.get("DailyLow", {}).get("TemperatureInfo", {}).get("AirTemperature") if isinstance(de.get("DailyLow"), dict) else None
            try:
                daily_high = float(dh) if dh not in (None, "-99", "-999", "", "-") else None
            except (ValueError, TypeError):
                daily_high = None
            try:
                daily_low = float(dl) if dl not in (None, "-99", "-999", "", "-") else None
            except (ValueError, TypeError):
                daily_low = None

        now_info = we.get("Now")
        precip_val = now_info.get("Precipitation") if isinstance(now_info, dict) else we.get("Precipitation")
        precip = observed_number(precip_val, 0)
        wind = observed_number(we.get("WindSpeed"), 0)
        humid = observed_number(we.get("RelativeHumidity"), 0, 100)

        # 天氣現象
        weather_desc = str(we.get("Weather", "") or "").strip()

        # 觀測時間
        obs_time = st.get("ObsTime")
        if isinstance(obs_time, dict):
            obs_time_str = obs_time.get("DateTime", "")
        else:
            obs_time_str = str(obs_time or "")

        rows.append({
            "stationId": str(st_id),
            "stationName": str(st_name).strip(),
            "countyName": normalizeCountyName(county),
            "townName": normalizeDistrictName(town),
            "lat": lat,
            "lon": lon,
            "temp": temp,
            "dailyHigh": daily_high,
            "dailyLow": daily_low,
            "precip": precip,
            "wind": wind,
            "humid": humid,
            "weather": weather_desc,
            "obsTime": obs_time_str,
        })

    df = pd.DataFrame(rows, columns=["stationId", "stationName", "countyName", "townName", "lat", "lon", "temp", "dailyHigh", "dailyLow", "precip", "wind", "humid", "weather", "obsTime"])
    # County observations remain useful even without station coordinates.
    df = df.reset_index(drop=True)
    return df


def parse_weather_warnings(raw_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """解析 CWA 天氣特報 JSON 資料 (W-C0033-002 或 W-C0033-001)."""
    if not isinstance(raw_json, dict):
        return []

    records = raw_json.get("records")
    if not records or not isinstance(records, dict):
        return []

    warnings: List[Dict[str, Any]] = []

    # 情況 1: W-C0033-002 格式 (records.record list)
    records_list = records.get("record", [])
    if isinstance(records_list, list):
        for rec in records_list:
            if not isinstance(rec, dict):
                continue
            dataset_info = rec.get("datasetInfo", {})
            title = dataset_info.get("datasetDescription", "天氣特報")
            valid_time = dataset_info.get("validTime", {})
            start_time = valid_time.get("startTime", "")
            end_time = valid_time.get("endTime", "")
            
            contents = rec.get("contents", {})
            content_dict = contents.get("content", {}) if isinstance(contents, dict) else {}
            content_text = content_dict.get("contentText", "").strip() if isinstance(content_dict, dict) else ""

            # 提煉主要簡要說明
            short_desc = ""
            if content_text:
                lines = [l.strip() for l in content_text.split("\n") if l.strip()]
                short_desc = lines[0] if lines else content_text
                if len(short_desc) > 80:
                    short_desc = short_desc[:77] + "..."

            warnings.append({
                "title": title,
                "startTime": start_time,
                "endTime": end_time,
                "description": short_desc or content_text or title,
                "fullText": content_text,
            })

    return warnings

