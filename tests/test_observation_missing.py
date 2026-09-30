"""Missing CWA readings must remain NULL through parsing and SQLite."""
import pandas as pd
import data_processor
import database


def test_missing_and_zero_weather_values_roundtrip(tmp_path):
    stations=[]
    for i, readings in enumerate([{},dict(AirTemperature=0,WindSpeed=0,RelativeHumidity=0,Now=dict(Precipitation=0)),dict(AirTemperature="-99",WindSpeed="-999",RelativeHumidity="NaN",Now=dict(Precipitation="-99"))]):
        stations.append(dict(StationId=str(i),StationName="Test",GeoInfo=dict(CountyName="臺北市",TownName="中正區",Coordinates=[dict(CoordinateName="WGS84",StationLatitude=25,StationLongitude=121)]),WeatherElement=readings))
    df=data_processor.parse_realtime_station_json(dict(records=dict(Station=stations)))
    assert df.loc[0,["temp","wind","precip","humid"]].isna().all()
    assert (df.loc[1,["temp","wind","precip","humid"]] == 0).all()
    assert df.loc[2,["temp","wind","precip","humid"]].isna().all()
    path=str(tmp_path / "observations.db")
    database.insert_station_observations(df,db_path=path)
    actual=database.get_station_observations(db_path=path).set_index("stationId")
    assert actual.loc["0",["temp","wind","precip","humid"]].isna().all()
    assert (actual.loc["1",["temp","wind","precip","humid"]] == 0).all()
