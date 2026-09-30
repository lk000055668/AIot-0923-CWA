import pandas as pd
from spatial_mapping import DistrictIndex, assign_station_districts
import map as weather_map


def feature(name, coordinates, kind="Polygon", county="甲縣"):
    return {"type":"Feature", "properties":{"COUNTYNAME":county,"TOWNNAME":name},
            "geometry":{"type":kind,"coordinates":coordinates}}


def square(x, y, size=2):
    return [[x,y],[x+size,y],[x+size,y+size],[x,y+size],[x,y]]


def index(*features):
    return DistrictIndex({"type":"FeatureCollection","features":list(features)})


def test_polygon_overrides_wrong_county_and_name():
    geo=index(feature("正確區",[square(120,24)]))
    df=pd.DataFrame([dict(lat=25,lon=121,countyName="錯縣",townName="錯區",stationName="正確區旁測站")])
    mapped=assign_station_districts(df,geo).iloc[0]
    assert (mapped.countyName,mapped.townName,mapped.mappingMethod)==("甲縣","正確區","polygon")
    assert (mapped.sourceCountyName,mapped.sourceTownName)==("錯縣","錯區")
    assert df.iloc[0].countyName=="錯縣"  # raw input is not overwritten


def test_holes_and_multipolygon_islands():
    geo=index(feature("離島區",[[square(120,24),square(120.5,24.5,.5)],[square(124,25)]],"MultiPolygon"))
    assert geo.locate(120.2,24.2)[2]=="polygon"
    assert geo.locate(120.7,24.7)[2]=="unmapped"  # inside a hole
    assert geo.locate(125,26)[2]=="polygon"  # second island
    assert geo.locate(120.5,24.7)[2]=="polygon"  # hole edge


def test_shared_edge_requires_explicit_cwa_disambiguation():
    geo=index(feature("西區",[square(120,24)]),feature("東區",[square(122,24)]))
    assert geo.locate(122,25)[2]=="ambiguous"
    assert geo.locate(122,25,"甲縣","東區")==("甲縣","東區","boundary_cwa")
    assert geo.locate(121,25,"甲縣","東區")==("甲縣","西區","polygon")


def test_outside_does_not_guess_from_station_name_or_nearest_polygon():
    geo=index(feature("東區",[square(120,24)]))
    assert geo.locate(123,25)==("","","unmapped")
    assert geo.locate(123,25,"甲縣","東區")==("甲縣","東區","cwa_fallback")
    assert geo.locate(123,25,"甲縣","不存在")[2]=="unmapped"


def test_grouping_uses_coordinates_and_preserves_per_metric_sources(monkeypatch):
    boundaries={"district":{"type":"FeatureCollection","features":[feature("中正區",[square(120,24)],county="臺北市")]}}
    geo=DistrictIndex(boundaries["district"])
    monkeypatch.setattr(weather_map,"load_boundaries",lambda:(boundaries,geo))
    rows=[dict(stationId="a",stationName="不相關站名",lat=25,lon=121,countyName="錯誤",townName="錯誤",temp=10,humid=None),
          dict(stationId="b",stationName="另一站",lat=25.1,lon=121.1,countyName="錯誤",townName="錯誤",temp=30,humid=80),
          dict(stationId="c",lat=25.2,lon=121.2,temp=None,humid=100)]
    m=weather_map.create_taiwan_realtime_weather_map(pd.DataFrame(rows))
    region=m.weather_data["datasets"]["temp"]["district"][0]
    assert region["name"]=="中正區" and region["value"]==20
    assert region["values"]=={"temp":20,"humid":90}
    assert region["counts"]=={"temp":2,"humid":2}
    assert region["station_ids"]==["station:a","station:b","station:c"]
    assert m.weather_data["datasets"]["humid"]["district"][0]["lat"]==region["lat"]
    assert m.weather_data["stations"][0]["sourceTownName"]=="錯誤"


def test_single_station_district_keeps_exact_observation(monkeypatch):
    boundaries={"district":{"type":"FeatureCollection","features":[feature("中正區",[square(120,24)],county="臺北市")]}}
    monkeypatch.setattr(weather_map,"load_boundaries",lambda:(boundaries,DistrictIndex(boundaries["district"])))
    m=weather_map.create_taiwan_realtime_weather_map(pd.DataFrame([dict(lat=25,lon=121,temp=26.8,humid=0)]))
    region=m.weather_data["datasets"]["temp"]["district"][0]
    assert region["value"]==26.8 and region["station_count"]==1
    assert region["values"]["humid"]==0


def test_fallback_station_label_stays_inside_district(monkeypatch):
    boundaries={"district":{"type":"FeatureCollection","features":[feature("中正區",[square(120,24),square(120.5,24.5,1)],county="臺北市")]}}
    geo=DistrictIndex(boundaries["district"])
    monkeypatch.setattr(weather_map,"load_boundaries",lambda:(boundaries,geo))
    m=weather_map.create_taiwan_realtime_weather_map(pd.DataFrame([dict(lat=20,lon=120,countyName="臺北市",townName="中正區",temp=26.8)]))
    region=m.weather_data["datasets"]["temp"]["district"][0]
    assert m.weather_data["stations"][0]["mappingMethod"]=="cwa_fallback"
    assert ("臺北市","中正區") in geo.candidates(region["lon"],region["lat"])
    assert region["value"]==26.8
