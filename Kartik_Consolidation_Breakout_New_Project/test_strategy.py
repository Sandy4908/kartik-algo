import pandas as pd
from backend.strategy import scan_symbol

def test_confirmed_breakout_has_buy_trigger_above_breakout_high():
    rows = []
    dates = pd.date_range("2026-01-01", periods=25, freq="D")
    for d in dates:
        rows.append({"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000})
    # 12-day consolidation
    for d in pd.date_range("2026-02-01", periods=12, freq="D"):
        rows.append({"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000})
    rows.append({"date": pd.Timestamp("2026-02-13"), "open": 101, "high": 104, "low": 100, "close": 103, "volume": 1600})
    result = scan_symbol(pd.DataFrame(rows), "TEST", 10, 15, 3.0, 2.0, 1.5, 20)
    assert result["signal"] == "Breakout Confirmed"
    assert result["breakout_candle_high"] == 104.0
    assert result["buy_trigger"] == 104.0
    assert result["consolidation_candles"] >= 10
