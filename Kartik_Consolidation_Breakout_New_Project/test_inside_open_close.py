import pandas as pd
from backend.strategy import scan_inside_open_close

def test_inside_open_close_breakout():
    rows = [
        ["2026-01-01",100,110,90,105,100],
        ["2026-01-02",102,115,85,108,100],
        ["2026-01-03",100,112,80,104,100],
        ["2026-01-04",101,114,82,109,100],
        ["2026-01-05",106,118,95,116,100],
    ]
    df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume"])
    result = scan_inside_open_close(df, "TEST", min_inside=3, max_n=10,
                                    entry_buffer=0.1, stop_buffer=0.1, risk_amount=1000)
    assert result["signal"] == "Inside Open Close Breakout"
    assert result["consolidation_candles"] == 3
    assert result["buy_trigger"] == 118.1
    assert result["stoploss"] == 94.9
    assert result["target1_rr"] == 3 and result["target2_rr"] == 6
