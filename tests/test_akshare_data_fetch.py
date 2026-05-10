from http.client import RemoteDisconnected

import pandas as pd
import pytest

from tradingagents.dataflows import akshare


class _EastmoneyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "klines": [
                    "2026-05-06,10.00,10.50,10.80,9.90,12345,13000000,9.00,5.00,0.50,2.10",
                    "2026-05-07,10.40,10.70,10.90,10.20,22345,24000000,6.67,1.90,0.20,3.20",
                ]
            }
        }


@pytest.mark.unit
def test_stock_data_falls_back_to_eastmoney_after_remote_disconnect(monkeypatch):
    def disconnected(*args, **kwargs):
        raise RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr(akshare.ak, "stock_zh_a_hist", disconnected)
    monkeypatch.setattr(akshare.requests, "get", lambda *args, **kwargs: _EastmoneyResponse())

    result = akshare.get_stock_data("002938", "2026-05-06", "2026-05-07")

    assert "Stock data for 002938" in result
    assert "2026-05-06,10.0,10.5,10.8,9.9" in result
    assert "RemoteDisconnected" not in result


@pytest.mark.unit
def test_long_window_indicator_returns_na_when_history_is_short(monkeypatch):
    df = pd.DataFrame({
        "日期": ["2026-05-06", "2026-05-07"],
        "开盘": [10.0, 10.4],
        "收盘": [10.5, 10.7],
        "最高": [10.8, 10.9],
        "最低": [9.9, 10.2],
        "成交量": [12345, 22345],
    })
    monkeypatch.setattr(akshare, "_fetch_a_stock_hist_df", lambda *args, **kwargs: df)

    result = akshare.get_indicators("002938", "close_200_sma", "2026-05-07", 30)

    assert "close_200_sma values" in result
    assert "N/A" in result
    assert "Error getting indicators" not in result
