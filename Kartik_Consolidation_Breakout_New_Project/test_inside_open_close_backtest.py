import pandas as pd
from backend.strategy import backtest_inside_open_close


def test_inside_open_close_backtest_two_targets():
    rows = [
        # Mother candle
        ["2026-01-01", 8, 10, 5, 8, 100],
        # Three consecutive candles whose open/close are inside mother range
        ["2026-01-02", 7, 9, 4, 8, 100],
        ["2026-01-03", 8, 10.5, 6, 9, 100],
        ["2026-01-04", 9, 10, 7, 8, 100],
        # Breakout close above mother high; entry = high + 0.2; SL = low - 0.1
        ["2026-01-05", 9, 11, 8.5, 10.5, 100],
        # Entry fill, no target/SL
        ["2026-01-06", 10.8, 12, 10.5, 11.5, 100],
        # First target
        ["2026-01-07", 11.5, 20.5, 11, 20, 100],
        # Second target
        ["2026-01-08", 20, 30, 19, 29, 100],
    ]
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    trades = backtest_inside_open_close(df, "TEST", min_inside=3, max_n=20,
                                        entry_buffer=0.2, stop_buffer=0.1,
                                        risk_amount=1000)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry"] == 11.2
    assert trade["exit_reason"] == "Target 2"
    assert trade["target1_quantity"] + trade["target2_quantity"] == trade["quantity"]
    assert trade["pnl"] > 0
