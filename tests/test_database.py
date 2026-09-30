"""Unit tests for database module."""

import os
import tempfile
import pytest
import pandas as pd
import database


@pytest.fixture
def temp_db():
    """建立臨時 SQLite 資料庫檔案供測試使用."""
    import gc
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database.init_db(db_path=path)
    yield path
    gc.collect()
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def test_init_db(temp_db):
    """測試資料表初始化."""
    with database.get_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='TemperatureForecasts';")
        row = cursor.fetchone()
        assert row is not None
        assert row["name"] == "TemperatureForecasts"


def test_insert_and_duplicate_prevention(temp_db):
    """測試資料寫入與防重複機制 (Upsert)."""
    df_first = pd.DataFrame([
        {"regionName": "中部地區", "dataDate": "2026-09-23", "minT": 20.0, "maxT": 28.0},
        {"regionName": "南部地區", "dataDate": "2026-09-23", "minT": 23.0, "maxT": 31.0},
    ])
    count1 = database.insert_weather_data(df_first, db_path=temp_db)
    assert count1 == 2

    df_all = database.get_weather_data(db_path=temp_db)
    assert len(df_all) == 2

    # 重複寫入相同地區與日期，但更新溫度
    df_second = pd.DataFrame([
        {"regionName": "中部地區", "dataDate": "2026-09-23", "minT": 22.0, "maxT": 29.5},
    ])
    count2 = database.insert_weather_data(df_second, db_path=temp_db)
    assert count2 == 1

    # 總筆數應依然為 2，且中部地區溫度已更新
    df_all_after = database.get_weather_data(db_path=temp_db)
    assert len(df_all_after) == 2

    central = database.get_weather_by_region("中部地區", db_path=temp_db)
    assert len(central) == 1
    assert central.iloc[0]["minT"] == 22.0
    assert central.iloc[0]["maxT"] == 29.5


def test_queries(temp_db):
    """測試依地區、日期及清單查詢功能."""
    test_data = pd.DataFrame([
        {"regionName": "北部地區", "dataDate": "2026-09-23", "minT": 19.0, "maxT": 26.0},
        {"regionName": "北部地區", "dataDate": "2026-09-24", "minT": 20.0, "maxT": 27.0},
        {"regionName": "東部地區", "dataDate": "2026-09-23", "minT": 21.0, "maxT": 28.0},
    ])
    database.insert_weather_data(test_data, db_path=temp_db)

    # 依地區
    north_df = database.get_weather_by_region("北部地區", db_path=temp_db)
    assert len(north_df) == 2

    # 依日期
    date_df = database.get_weather_by_date("2026-09-23", db_path=temp_db)
    assert len(date_df) == 2

    # 地區清單
    regions = database.get_distinct_regions(db_path=temp_db)
    assert "北部地區" in regions
    assert "東部地區" in regions

    # 日期清單
    dates = database.get_distinct_dates(db_path=temp_db)
    assert "2026-09-23" in dates
    assert "2026-09-24" in dates
