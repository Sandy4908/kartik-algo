import pandas as pd
import numpy as np

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    x = df.copy()
    x.columns = [str(c).strip().lower() for c in x.columns]
    if "date" not in x.columns:
        for candidate in ("timestamp", "datetime", "time"):
            if candidate in x.columns:
                x = x.rename(columns={candidate: "date"})
                break
    required = ["date", "open", "high", "low", "close"]
    missing = [c for c in required if c not in x.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    if "volume" not in x.columns:
        x["volume"] = np.nan
    x["date"] = pd.to_datetime(x["date"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["date", "open", "high", "low", "close"])
    return x.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def scan_symbol(df, symbol, consolidation_min=10, consolidation_max=15,
                max_range_pct=3.0, near_pct=2.0, volume_multiple=1.5,
                volume_period=20):
    x = normalize_ohlcv(df)
    if len(x) < consolidation_min + 1:
        return None

    current = x.iloc[-1]
    best = None
    # Test all permitted window sizes; choose the longest valid range.
    for n in range(consolidation_min, min(consolidation_max, len(x)-1) + 1):
        window = x.iloc[-(n+1):-1]  # breakout/current candle is excluded
        resistance = float(window["high"].max())
        support = float(window["low"].min())
        if support <= 0 or resistance <= support:
            continue
        range_pct = (resistance - support) / support * 100.0
        if range_pct <= max_range_pct:
            best = (n, resistance, support, range_pct)

    if best is None:
        return None

    n, resistance, support, range_pct = best
    close = float(current["close"])
    distance_pct = (resistance - close) / resistance * 100.0
    vol_avg = (
        x["volume"].iloc[-(volume_period+1):-1].mean()
        if len(x) >= volume_period + 1 else np.nan
    )
    current_vol = float(current["volume"]) if pd.notna(current["volume"]) else np.nan
    vol_ratio = (
        current_vol / vol_avg
        if pd.notna(current_vol) and pd.notna(vol_avg) and vol_avg > 0 else np.nan
    )
    price_broke = close > resistance
    volume_ok = pd.notna(vol_ratio) and vol_ratio >= volume_multiple

    if price_broke and volume_ok:
        signal = "Breakout Confirmed"
        note = "Daily close above consolidation resistance with >= configured volume multiple."
    elif price_broke and not volume_ok:
        signal = "Near Breakout"
        note = "Price closed above resistance, but volume confirmation is missing."
    elif 0 <= distance_pct <= near_pct:
        signal = "Near Breakout"
        note = "Close is within configured percentage below resistance."
    else:
        signal = "Consolidation Forming"
        note = "Valid tight range; price is not yet near resistance."

    breakout_high = float(current["high"]) if price_broke and volume_ok else None
    return {
        "symbol": str(symbol),
        "signal": signal,
        "date": current["date"].strftime("%Y-%m-%d"),
        "close": round(close, 2),
        "resistance": round(resistance, 2),
        "support": round(support, 2),
        "range_pct": round(range_pct, 2),
        "distance_to_resistance_pct": round(distance_pct, 2),
        "consolidation_candles": int(n),
        "volume": int(current_vol) if pd.notna(current_vol) else None,
        "average_volume": round(float(vol_avg), 0) if pd.notna(vol_avg) else None,
        "volume_ratio": round(float(vol_ratio), 2) if pd.notna(vol_ratio) else None,
        "breakout_candle_high": round(breakout_high, 2) if breakout_high is not None else None,
        "buy_trigger": round(breakout_high, 2) if breakout_high is not None else None,
        "note": note,
    }
