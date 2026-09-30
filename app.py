"""Map-first Taiwan weather application; data services remain unchanged."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import cwa_api
import data_processor
import database
import charts
import map as weather_map
from map_ui import APP_CSS, add_map_ui

st.set_page_config(page_title="台灣即時氣象", page_icon="🌤️", layout="wide", initial_sidebar_state="collapsed")

def update_all_cwa_data(api_key: Optional[str] = None, show_toast: bool = False) -> bool:
    """從 CWA API 抓取自動氣象站觀測、特報與預報資料並寫入 SQLite."""
    st.session_state["last_cwa_attempt_time"] = datetime.now()
    try:
        # 1. 抓取 O-A0003-001 (自動氣象站 360+ 站)
        raw_st = cwa_api.get_realtime_weather_data(api_key=api_key)
        df_st = data_processor.parse_realtime_station_json(raw_st)
        if df_st.empty:
            raise data_processor.DataProcessingError("CWA 本次未回傳有效測站資料。")
        cnt_st = database.insert_station_observations(df_st)

        # 2. 抓取 F-C0032-001 (天氣預報)
        try:
            raw_fc = cwa_api.get_weather_data(api_key=api_key, dataset_id="F-C0032-001")
            df_fc = data_processor.parse_weather_json(raw_fc)
            database.insert_weather_data(df_fc)
        except Exception:
            pass

        # 3. 抓取 W-C0033-002 (天氣特報)
        try:
            raw_warn = cwa_api.get_weather_warnings(api_key=api_key)
            warns = data_processor.parse_weather_warnings(raw_warn)
            st.session_state["weather_warnings"] = warns
        except Exception:
            st.session_state["weather_warnings"] = None

        st.session_state["sync_error"] = None
        if show_toast:
            st.toast(f"📡 自動更新成功！已同步 {cnt_st} 個測站即時資料", icon="✅")
        else:
            st.success(f"✅ 成功更新 {cnt_st} 個氣象測站之即時氣溫與觀測資料！")
        return True
    except ValueError as val_err:
        st.session_state["sync_error"] = str(val_err)
        return False
    except (cwa_api.CWAAPIError, data_processor.DataProcessingError, database.DatabaseError) as err:
        st.session_state["sync_error"] = str(err)
        return False
    except Exception as ex:
        st.session_state["sync_error"] = str(ex)
        return False


@st.dialog("資料與設定", width="large")
def settings_panel(df):
    settings, records, forecast = st.tabs(["資料同步", "測站資料", "預報趨勢"])
    with settings:
        st.caption("CWA O-A0003-001 · SQLite · 設定套用後回到地圖")
        st.text_input("CWA API Key（留白使用環境設定）", type="password", key="manual_api_key")
        st.toggle("自動更新", key="auto_update")
        st.selectbox("更新間隔（分鐘）", [1, 5, 10, 15, 30, 60], key="interval_minutes")
        if st.session_state.get("sync_error"):
            st.error(st.session_state["sync_error"])
        if st.button("立即同步 CWA"):
            key = st.session_state.get("manual_api_key") or cwa_api.get_api_key()
            if not key:
                st.error("請輸入 API Key 或設定 CWA_API_KEY。")
            elif update_all_cwa_data(key, show_toast=True):
                st.session_state["last_cwa_sync_time"] = datetime.now()
                st.rerun()
        if st.button("套用並回到地圖", type="primary"):
            st.rerun()
    with records:
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("下載測站 CSV", df.to_csv(index=False).encode("utf-8-sig"), "taiwan_weather.csv", "text/csv")
    with forecast:
        data = database.get_weather_data()
        if data.empty:
            st.info("尚無預報資料，請先同步 CWA。")
        else:
            region = st.selectbox("預報縣市", sorted(data["regionName"].unique()))
            st.plotly_chart(charts.create_temperature_line_chart(data[data["regionName"] == region], region), use_container_width=True)


def main():
    st.markdown(APP_CSS, unsafe_allow_html=True)
    database.init_db()
    database.init_station_db()
    for key, value in {"auto_update": True, "interval_minutes": 10, "manual_api_key": "", "last_cwa_sync_time": None}.items():
        # Keep dialog widget values alive while the dialog is closed.
        st.session_state[key] = st.session_state.get(key, value)
    effective_key = st.session_state["manual_api_key"] or cwa_api.get_api_key()
    if effective_key and not st.session_state.get("auto_sync_initialized"):
        st.session_state["auto_sync_initialized"] = True
        if update_all_cwa_data(effective_key, show_toast=True):
            st.session_state["last_cwa_sync_time"] = datetime.now()

    @st.fragment(run_every=timedelta(minutes=st.session_state["interval_minutes"]) if st.session_state["auto_update"] else None)
    def sync_worker():
        if effective_key and st.session_state["auto_update"]:
            previous = st.session_state.get("last_cwa_attempt_time")
            if previous is None or (datetime.now() - previous).total_seconds() >= st.session_state["interval_minutes"] * 60:
                if update_all_cwa_data(effective_key, show_toast=True):
                    st.session_state["last_cwa_sync_time"] = datetime.now()
                    st.rerun()
    sync_worker()
    df = database.get_station_observations()
    map_obj = weather_map.create_taiwan_realtime_weather_map(df)
    add_map_ui(map_obj, df, st.session_state.get("weather_warnings"),
               st.session_state.get("sync_error"), bool(effective_key and st.session_state["auto_update"]))
    with st.container(key="weather_map"):
        components.html(map_obj.get_root().render(), height=900, scrolling=False)
    with st.container(key="map_settings"):
        if st.button("⚙ 資料與設定", help="API、更新頻率、測站表格與預報"):
            settings_panel(df)


if __name__ == "__main__":
    main()
