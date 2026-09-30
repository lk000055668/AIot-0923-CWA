"""SQLite 資料庫管理模組.

負責 SQLite 資料庫連線、Schema 建立、氣溫資料防重複寫入 (Upsert)、
以及各種條件的 Parameterized SQL 查詢。
"""

from __future__ import annotations

import os
import sqlite3
from typing import List, Optional
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = os.getenv("DB_PATH", "data/data.db")


class DatabaseError(Exception):
    """資料庫操作自訂例外."""
    pass


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """建立並取得 SQLite 資料庫連線.

    若資料庫目錄不存在將自動建立。
    """
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # 啟用外鍵約束與 WAL 模式以提升效能
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except sqlite3.Error as e:
        raise DatabaseError(f"無法建立 SQLite 資料庫連線 ({db_path}): {e}") from e


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """初始化 SQLite 資料表結構 (Schema).

    建立 TemperatureForecasts 表格，包含 UNIQUE(regionName, dataDate) 以防重複插入。
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS TemperatureForecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        regionName TEXT NOT NULL,
        dataDate TEXT NOT NULL,
        minT REAL,
        maxT REAL,
        updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(regionName, dataDate)
    );
    """
    create_index_sql = """
    CREATE INDEX IF NOT EXISTS idx_region_date 
    ON TemperatureForecasts(regionName, dataDate);
    """

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(create_table_sql)
            cursor.execute(create_index_sql)
            conn.commit()
    except sqlite3.Error as e:
        raise DatabaseError(f"初始化資料庫失敗: {e}") from e


def insert_weather_data(df: pd.DataFrame, db_path: str = DEFAULT_DB_PATH) -> int:
    """將 DataFrame 氣溫預報資料寫入 SQLite 資料庫 (支援重複時更新).

    使用 INSERT OR REPLACE INTO 防止重複寫入造成資料膨脹。

    Args:
        df: 包含 regionName, dataDate, minT, maxT 欄位之 DataFrame。
        db_path: 資料庫路徑。

    Returns:
        int: 成功寫入/更新之資料筆數。
    """
    if df is None or df.empty:
        return 0

    init_db(db_path)

    insert_sql = """
    INSERT INTO TemperatureForecasts (regionName, dataDate, minT, maxT, updatedAt)
    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(regionName, dataDate) DO UPDATE SET
        minT = excluded.minT,
        maxT = excluded.maxT,
        updatedAt = CURRENT_TIMESTAMP;
    """

    records = []
    for _, row in df.iterrows():
        records.append((
            str(row.get("regionName", "")),
            str(row.get("dataDate", "")),
            float(row["minT"]) if pd.notnull(row.get("minT")) else None,
            float(row["maxT"]) if pd.notnull(row.get("maxT")) else None,
        ))

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(insert_sql, records)
            conn.commit()
            return len(records)
    except sqlite3.Error as e:
        raise DatabaseError(f"寫入氣溫資料失敗: {e}") from e


def get_weather_data(db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """查詢所有氣溫預報資料.

    Returns:
        pd.DataFrame: 完整資料表，依 regionName 與 dataDate 排序。
    """
    init_db(db_path)
    sql = """
    SELECT id, regionName, dataDate, minT, maxT, updatedAt
    FROM TemperatureForecasts
    ORDER BY regionName ASC, dataDate ASC;
    """
    try:
        with get_connection(db_path) as conn:
            df = pd.read_sql_query(sql, conn)
            return df
    except sqlite3.Error as e:
        raise DatabaseError(f"查詢氣溫資料失敗: {e}") from e


def get_weather_by_region(region_name: str, db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """依指定地區名稱查詢氣溫預報資料.

    Args:
        region_name: 地區名稱 (如 '北部地區', '中部地區')
        db_path: 資料庫檔案路徑

    Returns:
        pd.DataFrame: 該地區之氣溫預報。
    """
    init_db(db_path)
    sql = """
    SELECT id, regionName, dataDate, minT, maxT, updatedAt
    FROM TemperatureForecasts
    WHERE regionName = ?
    ORDER BY dataDate ASC;
    """
    try:
        with get_connection(db_path) as conn:
            df = pd.read_sql_query(sql, conn, params=(region_name,))
            return df
    except sqlite3.Error as e:
        raise DatabaseError(f"依地區查詢失敗 ({region_name}): {e}") from e


def get_weather_by_date(data_date: str, db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """依指定日期查詢全台各地區之氣溫預報資料.

    Args:
        data_date: 日期字串 (格式 YYYY-MM-DD)
        db_path: 資料庫檔案路徑

    Returns:
        pd.DataFrame: 該日期全台各地區預報。
    """
    init_db(db_path)
    sql = """
    SELECT id, regionName, dataDate, minT, maxT, updatedAt
    FROM TemperatureForecasts
    WHERE dataDate = ?
    ORDER BY regionName ASC;
    """
    try:
        with get_connection(db_path) as conn:
            df = pd.read_sql_query(sql, conn, params=(data_date,))
            return df
    except sqlite3.Error as e:
        raise DatabaseError(f"依日期查詢失敗 ({data_date}): {e}") from e


def get_weather_by_date_range(
    start_date: str,
    end_date: str,
    region_name: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """依日期範圍查詢氣溫預報資料 (可選擇指定地區)."""
    init_db(db_path)
    if region_name and region_name != "全部地區":
        sql = """
        SELECT id, regionName, dataDate, minT, maxT, updatedAt
        FROM TemperatureForecasts
        WHERE dataDate BETWEEN ? AND ? AND regionName = ?
        ORDER BY regionName ASC, dataDate ASC;
        """
        params: tuple = (start_date, end_date, region_name)
    else:
        sql = """
        SELECT id, regionName, dataDate, minT, maxT, updatedAt
        FROM TemperatureForecasts
        WHERE dataDate BETWEEN ? AND ?
        ORDER BY regionName ASC, dataDate ASC;
        """
        params = (start_date, end_date)

    try:
        with get_connection(db_path) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except sqlite3.Error as e:
        raise DatabaseError(f"範圍查詢失敗: {e}") from e


def get_distinct_regions(db_path: str = DEFAULT_DB_PATH) -> List[str]:
    """取得資料庫中所有不重複的地區清單."""
    init_db(db_path)
    sql = "SELECT DISTINCT regionName FROM TemperatureForecasts ORDER BY regionName ASC;"
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [row["regionName"] for row in rows]
    except sqlite3.Error as e:
        raise DatabaseError(f"取得地區清單失敗: {e}") from e


def get_distinct_dates(db_path: str = DEFAULT_DB_PATH) -> List[str]:
    """取得資料庫中所有不重複的預報日期清單 (由近到遠排序)."""
    init_db(db_path)
    sql = "SELECT DISTINCT dataDate FROM TemperatureForecasts ORDER BY dataDate ASC;"
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [row["dataDate"] for row in rows]
    except sqlite3.Error as e:
        raise DatabaseError(f"取得日期清單失敗: {e}") from e


def init_station_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """初始化即時測站觀測資料表 Schema."""
    create_station_table_sql = """
    CREATE TABLE IF NOT EXISTS StationObservations (
        stationId TEXT PRIMARY KEY,
        stationName TEXT NOT NULL,
        countyName TEXT,
        townName TEXT,
        lat REAL,
        lon REAL,
        temp REAL,
        dailyHigh REAL,
        dailyLow REAL,
        precip REAL,
        wind REAL,
        humid REAL,
        weather TEXT,
        obsTime TEXT,
        updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    create_index_sql = """
    CREATE INDEX IF NOT EXISTS idx_station_county 
    ON StationObservations(countyName);
    """
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(create_station_table_sql)
            cursor.execute(create_index_sql)
            conn.commit()
    except sqlite3.Error as e:
        raise DatabaseError(f"初始化測站資料庫失敗: {e}") from e


def insert_station_observations(df: pd.DataFrame, db_path: str = DEFAULT_DB_PATH) -> int:
    """寫入即時測站觀測資料至 SQLite (Upsert)."""
    if df is None or df.empty:
        return 0

    init_station_db(db_path)

    insert_sql = """
    INSERT INTO StationObservations (
        stationId, stationName, countyName, townName, lat, lon,
        temp, dailyHigh, dailyLow, precip, wind, humid, weather, obsTime, updatedAt
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(stationId) DO UPDATE SET
        stationName = excluded.stationName,
        countyName = excluded.countyName,
        townName = excluded.townName,
        lat = excluded.lat,
        lon = excluded.lon,
        temp = excluded.temp,
        dailyHigh = excluded.dailyHigh,
        dailyLow = excluded.dailyLow,
        precip = excluded.precip,
        wind = excluded.wind,
        humid = excluded.humid,
        weather = excluded.weather,
        obsTime = excluded.obsTime,
        updatedAt = CURRENT_TIMESTAMP;
    """

    records = []
    for _, row in df.iterrows():
        records.append((
            str(row.get("stationId", "")),
            str(row.get("stationName", "")),
            str(row.get("countyName", "")),
            str(row.get("townName", "")),
            float(row["lat"]) if pd.notnull(row.get("lat")) else None,
            float(row["lon"]) if pd.notnull(row.get("lon")) else None,
            float(row["temp"]) if pd.notnull(row.get("temp")) else None,
            float(row["dailyHigh"]) if pd.notnull(row.get("dailyHigh")) else None,
            float(row["dailyLow"]) if pd.notnull(row.get("dailyLow")) else None,
            float(row["precip"]) if pd.notnull(row.get("precip")) else None,
            float(row["wind"]) if pd.notnull(row.get("wind")) else None,
            float(row["humid"]) if pd.notnull(row.get("humid")) else None,
            str(row.get("weather", "")),
            str(row.get("obsTime", "")),
        ))

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(insert_sql, records)
            conn.commit()
            return len(records)
    except sqlite3.Error as e:
        raise DatabaseError(f"寫入測站觀測資料失敗: {e}") from e


def get_station_observations(county_name: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """查詢即時測站觀測資料 (可依縣市篩選)."""
    init_station_db(db_path)
    if county_name and county_name != "全部地區" and county_name != "全台灣":
        sql = "SELECT * FROM StationObservations WHERE countyName LIKE ? ORDER BY temp DESC;"
        params: tuple = (f"%{county_name}%",)
    else:
        sql = "SELECT * FROM StationObservations ORDER BY temp DESC;"
        params = ()

    try:
        with get_connection(db_path) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except sqlite3.Error as e:
        raise DatabaseError(f"查詢測站觀測資料失敗: {e}") from e


def get_station_summary_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """計算即時測站之極值統計指標 (最高溫、最低溫、最大雨量、最大風速等)."""
    df = get_station_observations(db_path=db_path)
    if df.empty:
        return {
            "max_temp": None, "max_temp_station": "--",
            "min_temp": None, "min_temp_station": "--",
            "max_precip": None, "max_precip_station": "--",
            "max_wind": None, "max_wind_station": "--",
            "total_stations": 0,
            "obs_time": "--",
        }

    valid_temp = df[df["temp"].notnull()]
    if not valid_temp.empty:
        max_t_row = valid_temp.loc[valid_temp["temp"].idxmax()]
        min_t_row = valid_temp.loc[valid_temp["temp"].idxmin()]
        max_temp = float(max_t_row["temp"])
        max_temp_st = f"{max_t_row['stationName']} ({max_t_row['countyName']})" if max_t_row['countyName'] else str(max_t_row['stationName'])
        min_temp = float(min_t_row["temp"])
        min_temp_st = f"{min_t_row['stationName']} ({min_t_row['countyName']})" if min_t_row['countyName'] else str(min_t_row['stationName'])
    else:
        max_temp, max_temp_st = None, "--"
        min_temp, min_temp_st = None, "--"

    valid_precip = df[df["precip"].notnull()]
    if not valid_precip.empty:
        max_p_row = valid_precip.loc[valid_precip["precip"].idxmax()]
        max_precip = float(max_p_row["precip"])
        max_precip_st = f"{max_p_row['stationName']}"
    else:
        max_precip, max_precip_st = 0.0, "--"

    valid_wind = df[df["wind"].notnull()]
    if not valid_wind.empty:
        max_w_row = valid_wind.loc[valid_wind["wind"].idxmax()]
        max_wind = float(max_w_row["wind"])
        max_wind_st = f"{max_w_row['stationName']}"
    else:
        max_wind, max_wind_st = 0.0, "--"

    obs_times = df["obsTime"].dropna()
    latest_obs = str(obs_times.iloc[0]) if not obs_times.empty else "--"

    return {
        "max_temp": max_temp,
        "max_temp_station": max_temp_st,
        "min_temp": min_temp,
        "min_temp_station": min_temp_st,
        "max_precip": max_precip,
        "max_precip_station": max_precip_st,
        "max_wind": max_wind,
        "max_wind_station": max_wind_st,
        "total_stations": len(df),
        "obs_time": latest_obs,
    }

