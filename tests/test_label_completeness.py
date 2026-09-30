"""Region-first regression: coordinate failures must not erase county readings."""
import pandas as pd
import map as weather_map
from spatial_mapping import DistrictIndex
from region_names import normalizeCountyName, normalizeDistrictName
from data_processor import parse_realtime_station_json


def test_all_regions_and_geometry_anchors_exist_without_weather():
    payload = weather_map.create_taiwan_realtime_weather_map(pd.DataFrame()).weather_data
    for kind, total in [("county", 22), ("district", 368)]:
        regions = payload["regions"][kind]
        index = DistrictIndex(payload["boundaries"][kind])
        assert len(regions) == total
        for region in regions:
            assert region["status"] == "NO DATA"
            assert (region["county"], region["district"]) in index.candidates(region["lon"], region["lat"])


def test_raw_county_survives_unmapped_station_and_invalid_coordinates():
    rows = [dict(stationId=str(i), countyName=" 台\u3000北市 ", townName="不存在", lat=lat, lon=lon, temp=temp)
            for i, (lat, lon, temp) in enumerate([(None, None, 10), (0, 0, 30), (None, None, ""),
                                                  (None, None, float("inf")), (None, None, "NaN")])]
    payload = weather_map.create_taiwan_realtime_weather_map(pd.DataFrame(rows)).weather_data
    county = payload["datasets"]["temp"]["county"]
    assert len(county) == 1 and county[0]["name"] == "臺北市"
    assert county[0]["value"] == 20 and county[0]["station_count"] == 2
    assert payload["datasets"]["temp"]["district"] == []


def test_all_counties_render_from_raw_names_independent_of_spatial_join():
    boundaries, _ = weather_map.load_boundaries()
    rows = [dict(stationId=str(i), countyName=f["properties"]["COUNTYNAME"].replace("臺", "台"),
                 townName="", temp=20, lat=None, lon=None)
            for i, f in enumerate(boundaries["county"]["features"])]
    payload = weather_map.create_taiwan_realtime_weather_map(pd.DataFrame(rows)).weather_data
    assert len(payload["datasets"]["temp"]["county"]) == 22
    assert not payload["datasets"]["temp"]["district"]


def test_parser_keeps_county_temperature_without_coordinates():
    df = parse_realtime_station_json({"records": {"Station": [
        {"StationId": "a", "GeoInfo": {"CountyName": "台北市"}, "WeatherElement": {"AirTemperature": 25}}
    ]}})
    assert len(df) == 1 and df.iloc[0].temp == 25
    assert df.iloc[0].countyName == "臺北市"
    assert normalizeCountyName(" 台\u3000北市 ") == "臺北市"
    assert normalizeDistrictName(" 台 東市 ") == "臺東市"
