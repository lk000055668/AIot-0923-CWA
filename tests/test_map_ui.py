"""Map payload, missing-data, rendering order and injection regressions."""
import pandas as pd
import map as weather_map
from map_ui import add_map_ui


def observation(**changes):
    row = dict(stationId="one", stationName="測站", countyName="臺北市", townName="中正區", lat=25, lon=121.5, temp=25.2)
    row.update(changes)
    return row


def test_empty_map_has_no_weather_options_or_values():
    m = weather_map.create_taiwan_realtime_weather_map(pd.DataFrame())
    add_map_ui(m, pd.DataFrame())
    html = m.get_root().render()
    assert not m.weather_data["layers"]
    assert "尚無有效氣象觀測" in html
    assert "示範資料" not in html
    assert html.index("var " + m.get_name() + " = L.map") < html.index("const map = " + m.get_name())


def test_station_and_warning_text_cannot_end_script():
    malicious = "</script><script>alert(1)</script>"
    df = pd.DataFrame([observation(stationName=malicious)])
    m = weather_map.create_taiwan_realtime_weather_map(df)
    add_map_ui(m, df, warnings=[dict(title=malicious, description=malicious)])
    html = m.get_root().render()
    assert malicious not in html
    assert "bindPopup" in html


def test_metrics_use_independent_valid_samples():
    df = pd.DataFrame([observation(temp=10,humid=None),observation(stationId="two",temp=30,humid=80),observation(stationId="three",temp=None,humid=100)])
    m = weather_map.create_taiwan_realtime_weather_map(df)
    assert set(m.weather_data["layers"]) == {"temp","humid"}
    assert m.weather_data["datasets"]["temp"]["county"][0]["value"] == 20
    assert m.weather_data["datasets"]["humid"]["district"][0]["value"] == 90
    assert len(m.weather_data["stations"]) == 3


def test_zero_is_real_and_missing_values_do_not_enable_layers():
    df = pd.DataFrame([observation(temp=float("nan"),precip=0,wind=-99,humid=float("inf"))])
    m = weather_map.create_taiwan_realtime_weather_map(df)
    assert set(m.weather_data["layers"]) == {"precip"}
    assert m.weather_data["datasets"]["precip"]["county"][0]["value"] == 0
    assert "NaN" not in m.get_root().render()


def test_legend_bins_match_color_ranges_and_boundaries_are_loaded():
    for spec in weather_map.WEATHER_LAYERS.values():
        assert len(spec["colors"]) == len(spec["breaks"]) + 1
        assert sorted(spec["breaks"]) == spec["breaks"]
    m = weather_map.create_taiwan_realtime_weather_map(pd.DataFrame())
    assert len(m.weather_data["boundaries"]["county"]["features"]) == 22
    assert len(m.weather_data["boundaries"]["district"]["features"]) == 368


def test_summary_uses_actual_extrema_and_places_only():
    df = pd.DataFrame([observation(stationName="甲站",temp=10),observation(stationId="two",stationName="乙站",temp=30)])
    m = weather_map.create_taiwan_realtime_weather_map(df)
    add_map_ui(m,df)
    html=m.get_root().render()
    assert "甲站" in html and "乙站" in html
    assert "最大雨量" not in html
