"""Unit tests for data_processor module."""

import pytest
import pandas as pd
from data_processor import parse_weather_json, normalize_weather_data, DataProcessingError


@pytest.fixture
def sample_cwa_json():
    """模擬 CWA API 回傳之 JSON 結構."""
    return {
        "success": "true",
        "result": {"resource_id": "F-C0032-005"},
        "records": {
            "locations": [
                {
                    "location": [
                        {
                            "locationName": "北部地區",
                            "weatherElement": [
                                {
                                    "elementName": "MinT",
                                    "time": [
                                        {
                                            "startTime": "2026-09-23 00:00:00",
                                            "endTime": "2026-09-23 12:00:00",
                                            "elementValue": [{"value": "20", "measures": "攝氏度"}],
                                        },
                                        {
                                            "startTime": "2026-09-24 00:00:00",
                                            "endTime": "2026-09-24 12:00:00",
                                            "elementValue": [{"value": "21", "measures": "攝氏度"}],
                                        },
                                    ],
                                },
                                {
                                    "elementName": "MaxT",
                                    "time": [
                                        {
                                            "startTime": "2026-09-23 12:00:00",
                                            "endTime": "2026-09-23 23:59:59",
                                            "elementValue": [{"value": "28", "measures": "攝氏度"}],
                                        },
                                        {
                                            "startTime": "2026-09-24 12:00:00",
                                            "endTime": "2026-09-24 23:59:59",
                                            "elementValue": [{"value": "30", "measures": "攝氏度"}],
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            "locationName": "南部地區",
                            "weatherElement": [
                                {
                                    "elementName": "MinT",
                                    "time": [
                                        {
                                            "startTime": "2026-09-23 00:00:00",
                                            "endTime": "2026-09-23 12:00:00",
                                            "elementValue": [{"value": "24", "measures": "攝氏度"}],
                                        }
                                    ],
                                },
                                {
                                    "elementName": "MaxT",
                                    "time": [
                                        {
                                            "startTime": "2026-09-23 12:00:00",
                                            "endTime": "2026-09-23 23:59:59",
                                            "elementValue": [{"value": "32", "measures": "攝氏度"}],
                                        }
                                    ],
                                },
                            ],
                        },
                    ]
                }
            ]
        },
    }


def test_parse_weather_json_success(sample_cwa_json):
    """測試正常 CWA JSON 的解析結果."""
    df = parse_weather_json(sample_cwa_json)

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert set(["regionName", "dataDate", "minT", "maxT"]).issubset(df.columns)

    # 檢查北部地區 2026-09-23 數值
    north_23 = df[(df["regionName"] == "北部地區") & (df["dataDate"] == "2026-09-23")]
    assert len(north_23) == 1
    assert north_23.iloc[0]["minT"] == 20.0
    assert north_23.iloc[0]["maxT"] == 28.0

    # 檢查南部地區
    south_23 = df[(df["regionName"] == "南部地區") & (df["dataDate"] == "2026-09-23")]
    assert len(south_23) == 1
    assert south_23.iloc[0]["minT"] == 24.0
    assert south_23.iloc[0]["maxT"] == 32.0


def test_parse_weather_json_invalid():
    """測試非預期或空 JSON 的錯誤處理."""
    with pytest.raises(DataProcessingError):
        parse_weather_json({})

    with pytest.raises(DataProcessingError):
        parse_weather_json({"records": {}})


def test_normalize_weather_data():
    """測試資料正規化函式."""
    raw_data = {
        "regionName": [" 北部地區 ", "中部地區", ""],
        "dataDate": ["2026-09-23", "2026-09-23", "2026-09-23"],
        "minT": ["20.5", "invalid", 18.0],
        "maxT": ["28.0", "30", None],
    }
    df_raw = pd.DataFrame(raw_data)
    df_norm = normalize_weather_data(df_raw)

    assert len(df_norm) == 2  # 空地區名稱已被濾除
    assert df_norm.iloc[0]["regionName"] in ("北部地區", "中部地區")
    assert isinstance(df_norm["minT"].iloc[0], (float, int))


def test_parse_realtime_station_json():
    """測試解析自動氣象站即時資料 (O-A0003-001)."""
    from data_processor import parse_realtime_station_json
    sample_station_json = {
        "success": "true",
        "records": {
            "Station": [
                {
                    "StationId": "466940",
                    "StationName": "基隆",
                    "GeoInfo": {
                        "Coordinates": [
                            {"CoordinateName": "WGS84", "StationLatitude": "25.1333", "StationLongitude": "121.7404"}
                        ],
                        "CountyName": "基隆市",
                        "TownName": "仁愛區",
                    },
                    "WeatherElement": {
                        "AirTemperature": "28.5",
                        "Weather": "晴",
                        "Now": {"Precipitation": "0.0"},
                        "WindSpeed": "4.6",
                        "RelativeHumidity": "65",
                        "DailyExtreme": {
                            "DailyHigh": {"TemperatureInfo": {"AirTemperature": "29.2"}},
                            "DailyLow": {"TemperatureInfo": {"AirTemperature": "24.1"}},
                        },
                    },
                    "ObsTime": "2026-09-23 11:20:00",
                }
            ]
        }
    }
    df = parse_realtime_station_json(sample_station_json)
    assert len(df) == 1
    assert df.iloc[0]["stationName"] == "基隆"
    assert df.iloc[0]["temp"] == 28.5
    assert df.iloc[0]["dailyHigh"] == 29.2
    assert df.iloc[0]["dailyLow"] == 24.1


def test_parse_weather_warnings():
    """測試解析天氣警特報資料 (W-C0033-002)."""
    from data_processor import parse_weather_warnings
    sample_warn_json = {
        "success": "true",
        "records": {
            "record": [
                {
                    "datasetInfo": {
                        "datasetDescription": "陸上強風特報",
                        "validTime": {"startTime": "2026-09-23 17:00:00", "endTime": "2026-09-23 23:00:00"},
                    },
                    "contents": {
                        "content": {"contentText": "風力增強，請注意安全。"}
                    }
                }
            ]
        }
    }
    warns = parse_weather_warnings(sample_warn_json)
    assert len(warns) == 1
    assert warns[0]["title"] == "陸上強風特報"
    assert "風力增強" in warns[0]["description"]

