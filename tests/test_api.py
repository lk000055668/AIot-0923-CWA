"""Unit tests for cwa_api module."""

from unittest.mock import patch, MagicMock
import pytest
import requests
import cwa_api


def test_missing_api_key():
    """測試未提供 API Key 且環境變數為空時拋出 ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError) as exc_info:
            cwa_api.get_weather_data(api_key=None)
        assert "尚未設定 CWA_API_KEY" in str(exc_info.value)


@patch("requests.Session.get")
def test_get_weather_data_success(mock_get):
    """測試成功呼叫 CWA API 並解析回傳 JSON."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": "true",
        "records": {"locations": []},
    }
    mock_get.return_value = mock_response

    data = cwa_api.get_weather_data(api_key="mock_test_key")
    assert data["success"] == "true"
    assert "records" in data
    mock_get.assert_called_once()


@patch("requests.Session.get")
def test_get_weather_data_unauthorized(mock_get):
    """測試 API Key 錯誤或未授權時的例外處理."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_get.return_value = mock_response

    with pytest.raises(cwa_api.CWAAPIError) as exc_info:
        cwa_api.get_weather_data(api_key="invalid_key", max_retries=1)
    assert "401" in str(exc_info.value) or "授權失敗" in str(exc_info.value)


@patch("requests.Session.get")
def test_get_weather_data_timeout(mock_get):
    """測試網路逾時的例外處理."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

    with pytest.raises(cwa_api.CWAAPIError) as exc_info:
        cwa_api.get_weather_data(api_key="mock_key", max_retries=2, retry_delay=0.01)
    assert "Timeout" in str(exc_info.value) or "逾時" in str(exc_info.value)
