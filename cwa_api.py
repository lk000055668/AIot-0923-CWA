"""中央氣象署 (CWA) Open Data API 串接模組.

負責向 CWA Open Data API 發送請求、處理授權認證、重試機制與例外處理，
並回傳原始 JSON 資料。
"""

from __future__ import annotations

import os
import ssl
import time
from typing import Any, Dict, Optional
import requests
from dotenv import load_dotenv

# 自動載入 .env 檔案中的環境變數
load_dotenv()

BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
DEFAULT_DATASET_ID = "F-C0032-001"  # 台灣各地36小時天氣預報 (22 縣市)


class CWAAPIError(Exception):
    """CWA API 自訂例外類別."""
    pass


class _SSLAdapter(requests.adapters.HTTPAdapter):
    """自訂 SSL HTTPAdapter 以相容 OpenSSL 3.x 憑證驗證 (相容 Windows/Python 3.14)."""

    def __init__(self, ssl_context: Optional[ssl.SSLContext] = None, **kwargs: Any) -> None:
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["ssl_context"] = self.ssl_context
        super().init_poolmanager(*args, **kwargs)


def _create_session() -> requests.Session:
    """建立具備適當 SSL Context 設定的 requests.Session."""
    session = requests.Session()
    try:
        ctx = ssl.create_default_context()
        # 關閉 OpenSSL 3.x 過於嚴格的 X509 檢查，避免台灣政府憑證鏈缺少 Subject Key Identifier 時報錯
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        adapter = _SSLAdapter(ssl_context=ctx)
        session.mount("https://", adapter)
    except Exception:
        pass
    return session


def get_api_key() -> Optional[str]:
    """從環境變數取得 CWA API Key."""
    return os.getenv("CWA_API_KEY") or None


def get_weather_data(
    api_key: Optional[str] = None,
    dataset_id: Optional[str] = None,
    timeout: int = 15,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Dict[str, Any]:
    """向中央氣象署 CWA API 請求天氣預報資料.

    Args:
        api_key: CWA API 授權金鑰。若未提供則嘗試由環境變數 CWA_API_KEY 取得。
        dataset_id: 資料集識別碼，預設為 F-C0032-001 (各地36小時天氣預報)。
        timeout: 連線與讀取逾時秒數 (預設 15 秒)。
        max_retries: 遇網路錯誤時的最大重試次數。
        retry_delay: 重試間隔秒數。

    Returns:
        Dict[str, Any]: CWA API 回傳的原始 JSON 資料字典。

    Raises:
        ValueError: 未設定或傳入 API Key 時拋出。
        CWAAPIError: HTTP 錯誤、API 授權失敗、逾時、SSL 或連線錯誤時拋出。
    """
    key = api_key or get_api_key()
    if not key or key.strip() == "" or key.strip() == "your_cwa_api_key_here":
        raise ValueError("尚未設定 CWA_API_KEY，請先設定 .env 或手動輸入金鑰。")

    dataset = dataset_id or os.getenv("CWA_DATASET_ID", DEFAULT_DATASET_ID)
    url = f"{BASE_URL}/{dataset}"

    headers = {
        "Authorization": key.strip(),
        "Accept": "application/json",
        "User-Agent": "TaiwanWeatherDashboard/1.0",
    }

    params = {
        "format": "JSON",
    }

    session = _create_session()
    last_exception: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )

            # 檢查 HTTP 狀態碼
            if response.status_code == 401:
                raise CWAAPIError(
                    f"HTTP 401 (授權失敗): CWA API 授權碼無效或尚未啟用。請確認 CWA_API_KEY 是否正確。"
                )
            elif response.status_code == 403:
                raise CWAAPIError(
                    f"HTTP 403 (存取被拒): CWA API 存取受限，請確認金鑰權限。"
                )
            elif response.status_code == 404:
                raise CWAAPIError(
                    f"HTTP 404 (找不到資源): 找不到資料集 '{dataset}'。請確認 CWA_DATASET_ID 是否正確 (建議使用 F-C0032-001)。"
                )
            elif response.status_code >= 500:
                raise CWAAPIError(
                    f"HTTP {response.status_code} (伺服器錯誤): CWA 氣象署伺服器異常，請稍後再試。"
                )

            response.raise_for_status()

            # 解析 JSON
            try:
                data = response.json()
            except ValueError as json_err:
                raise CWAAPIError(f"JSON 解析失敗: 無法解析 CWA API 回傳之 JSON ({json_err})") from json_err

            # 驗證 CWA 回傳 success 狀態
            if isinstance(data, dict):
                success_flag = str(data.get("success", "")).lower()
                if success_flag == "false":
                    error_msg = data.get("message", "未知 API 錯誤")
                    raise CWAAPIError(f"CWA API 回應失敗: {error_msg}")

            return data

        except requests.exceptions.SSLError as ssl_err:
            last_exception = ssl_err
            raise CWAAPIError(
                f"SSLError (SSL 憑證驗證失敗): 無法與 CWA 伺服器建立安全連線 ({ssl_err})"
            ) from ssl_err

        except requests.exceptions.Timeout as timeout_err:
            last_exception = timeout_err
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)
                continue
            raise CWAAPIError(
                f"Timeout (連線逾時): 連線至 CWA API 逾時 ({timeout} 秒)。請檢查網路連線狀態。"
            ) from timeout_err

        except requests.exceptions.ConnectionError as conn_err:
            last_exception = conn_err
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)
                continue
            raise CWAAPIError(
                f"ConnectionError (網路/DNS 連線失敗): 無法連線至 CWA API 伺服器 ({conn_err})"
            ) from conn_err

        except requests.exceptions.HTTPError as http_err:
            raise CWAAPIError(f"HTTPError: {http_err}") from http_err

    raise CWAAPIError(f"CWA API 請求重試 {max_retries} 次均失敗: {type(last_exception).__name__} - {last_exception}")


def get_realtime_weather_data(
    api_key: Optional[str] = None,
    timeout: int = 15,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Dict[str, Any]:
    """向中央氣象署 CWA API 請求自動氣象站即時觀測資料 (O-A0003-001 全台 360+ 測站).

    Returns:
        Dict[str, Any]: CWA API 回傳的原始 JSON 資料字典。
    """
    return get_weather_data(
        api_key=api_key,
        dataset_id="O-A0003-001",
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


def get_weather_warnings(
    api_key: Optional[str] = None,
    timeout: int = 10,
    max_retries: int = 2,
    retry_delay: float = 1.0,
) -> Dict[str, Any]:
    """向中央氣象署 CWA API 請求即時天氣警特報資料 (W-C0033-002).

    Returns:
        Dict[str, Any]: CWA API 回傳的警特報 JSON 資料。
    """
    return get_weather_data(
        api_key=api_key,
        dataset_id="W-C0033-002",
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )

