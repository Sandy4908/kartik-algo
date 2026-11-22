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


def scan_inside_open_close(df: pd.DataFrame, symbol: str, min_inside=3, max_n=20,
                          entry_buffer=0.0, stop_buffer=0.0, risk_amount=1000.0,
                          target1_rr=3.0, target2_rr=6.0):
    """Inside Open Close: recent consecutive bars' open/close stay within mother range;
    latest completed candle closes above mother high. Returns a breakout setup only.
    """
    x = normalize_ohlcv(df)
    if len(x) < min_inside + 2:
        return None
    breakout = x.iloc[-1]
    # Mother can be at most max_n candles behind the breakout bar.
    max_age = min(int(max_n), len(x) - 1)
    for age in range(min_inside + 1, max_age + 1):
        mother_idx = len(x) - 1 - age
        mother = x.iloc[mother_idx]
        inside = x.iloc[mother_idx + 1:-1]
        if len(inside) < min_inside:
            continue
        hi, lo = float(mother.high), float(mother.low)
        # Open and close of EVERY intervening candle must be strictly inside
        # (inclusive bounds) mother high/low. Their wicks may cross the range.
        valid = ((inside.open >= lo) & (inside.open <= hi) &
                 (inside.close >= lo) & (inside.close <= hi)).all()
        if not valid:
            continue
        close = float(breakout.close)
        if close <= hi:
            continue
        bh, bl = float(breakout.high), float(breakout.low)
        entry = bh + float(entry_buffer)
        sl = bl - float(stop_buffer)
        risk_per_share = entry - sl
        if entry <= 0 or sl < 0 or risk_per_share <= 0:
            continue
        qty = max(0, int(float(risk_amount) // risk_per_share))
        half = qty // 2
        return {
            "symbol": str(symbol), "signal": "Inside Open Close Breakout",
            "date": breakout.date.strftime("%Y-%m-%d"), "close": round(close, 2),
            "resistance": round(hi, 2), "support": round(lo, 2),
            "range_pct": round((hi-lo)/lo*100, 2) if lo > 0 else None,
            "distance_to_resistance_pct": round((hi-close)/hi*100, 2) if hi else None,
            "consolidation_candles": int(len(inside)),
            "mother_candle_date": mother.date.strftime("%Y-%m-%d"),
            "mother_high": round(hi, 2), "mother_low": round(lo, 2),
            "breakout_candle_high": round(bh, 2), "breakout_candle_low": round(bl, 2),
            "buy_trigger": round(entry, 2), "stoploss": round(sl, 2),
            "risk_per_share": round(risk_per_share, 2), "risk_amount": round(float(risk_amount), 2),
            "quantity": qty, "target1_quantity": half, "target2_quantity": qty-half,
            "target1": round(entry + risk_per_share*float(target1_rr), 2),
            "target2": round(entry + risk_per_share*float(target2_rr), 2),
            "target1_rr": float(target1_rr), "target2_rr": float(target2_rr),
            "note": "Latest completed candle closed above mother high after consecutive inside open/close candles."
        }
    return None



def backtest_inside_open_close(df: pd.DataFrame, symbol: str, min_inside=3, max_n=20,
                              entry_buffer=0.0, stop_buffer=0.0, risk_amount=1000.0,
                              target1_rr=3.0, target2_rr=6.0):
    """Historical OHLC simulation for Inside Open Close, with conservative intrabar SL priority."""
    x = normalize_ohlcv(df)
    trades = []
    i = max(int(min_inside) + 1, 1)
    while i < len(x) - 1:
        setup = scan_inside_open_close(
            x.iloc[:i + 1], symbol, min_inside=min_inside, max_n=max_n,
            entry_buffer=entry_buffer, stop_buffer=stop_buffer,
            risk_amount=risk_amount, target1_rr=target1_rr, target2_rr=target2_rr)
        if not setup:
            i += 1
            continue
        entry = float(setup['buy_trigger']); sl = float(setup['stoploss'])
        qty = int(setup['quantity']); q1=int(setup['target1_quantity']); q2=int(setup['target2_quantity'])
        if qty <= 0 or entry <= sl:
            i += 1; continue
        t1=float(setup['target1']); t2=float(setup['target2'])
        entry_idx=None
        # Entry is a stop-buy above breakout candle; only subsequent bars can fill.
        for j in range(i+1, len(x)):
            if float(x.iloc[j]['high']) >= entry:
                entry_idx=j; break
        if entry_idx is None:
            i += 1; continue
        remaining=qty; pnl=0.0; t1_done=False; exit_idx=entry_idx; exit_reason='Period End'
        for j in range(entry_idx, len(x)):
            bar=x.iloc[j]; lo=float(bar['low']); hi=float(bar['high'])
            exit_idx=j
            # Conservative assumption if SL and target coexist in one OHLC candle.
            if lo <= sl:
                pnl += remaining*(sl-entry); remaining=0; exit_reason='Stoploss'; break
            if not t1_done and hi >= t1 and q1>0:
                pnl += q1*(t1-entry); remaining-=q1; t1_done=True
            if remaining>0 and hi >= t2:
                pnl += remaining*(t2-entry); remaining=0; exit_reason='Target 2'; break
        if remaining>0:
            last=float(x.iloc[exit_idx]['close'])
            pnl += remaining*(last-entry)
            if t1_done: exit_reason='Target 1 + Period End'
        trades.append({
            'symbol':str(symbol), 'mother_date':setup.get('mother_candle_date'),
            'signal_date':setup.get('date'), 'entry_date':x.iloc[entry_idx]['date'].strftime('%Y-%m-%d %H:%M'),
            'exit_date':x.iloc[exit_idx]['date'].strftime('%Y-%m-%d %H:%M'),
            'entry':round(entry,2),'stoploss':round(sl,2),'target1':round(t1,2),'target2':round(t2,2),
            'quantity':qty,'target1_quantity':q1,'target2_quantity':q2,
            'exit_reason':exit_reason,'pnl':round(pnl,2),'risk_amount':round(float(risk_amount),2),
            'invested':round(entry*qty,2),'return_pct':round(pnl/(entry*qty)*100,2) if entry*qty else 0
        })
        i=max(i+1, exit_idx+1)
    return trades
