"""Zerodha WebSocket ticker and local candle aggregator."""
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from kiteconnect import KiteTicker
from backend.candle_cache import save_frame

IST=ZoneInfo("Asia/Kolkata")
class LiveCandleStream:
    def __init__(self):
        self.lock=threading.RLock(); self.ticker=None; self.tokens=set(); self.connected=False
        self.last_tick_volume={}; self.candles={}; self.last_message=None; self.error=None
    def start(self, api_key, access_token, instruments, symbol_by_token):
        tokens=[int(x["instrument_token"]) for x in instruments]
        with self.lock:
            if self.ticker and self.tokens==set(tokens) and self.connected: return
            old=self.ticker; self.connected=False; self.tokens=set(tokens)
        if old:
            try: old.close()
            except Exception: pass
        ticker=KiteTicker(api_key,access_token)
        self.ticker=ticker
        def on_connect(ws,response):
            try:
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_FULL,tokens)
                with self.lock: self.connected=True; self.error=None
            except Exception as e:
                with self.lock: self.error=str(e)
        def on_ticks(ws,ticks):
            now=datetime.now(IST); updated=[]
            for tick in ticks:
                token=int(tick.get("instrument_token",0)); price=tick.get("last_price")
                if not token or price is None: continue
                stamp=tick.get("last_trade_time") or tick.get("timestamp") or now
                if not isinstance(stamp,datetime):
                    try: stamp=datetime.fromisoformat(str(stamp))
                    except Exception: stamp=now
                if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=IST)
                stamp=stamp.astimezone(IST).replace(tzinfo=None)
                cum=float(tick.get("volume",0) or 0); prev=self.last_tick_volume.get(token,cum)
                delta=max(0,cum-prev) if cum>=prev else cum
                self.last_tick_volume[token]=cum
                sym=symbol_by_token.get(token,str(token))
                for interval,mins in (("5minute",5),("15minute",15),("60minute",60),("day",1440)):
                    bucket=stamp.replace(hour=stamp.hour,minute=(stamp.minute//mins)*mins,second=0,microsecond=0) if mins<1440 else stamp.replace(hour=0,minute=0,second=0,microsecond=0)
                    key=(token,interval); c=self.candles.get(key)
                    if c is None or c["date"]!=bucket:
                        c={"date":bucket,"open":float(price),"high":float(price),"low":float(price),"close":float(price),"volume":delta}
                        self.candles[key]=c
                    else:
                        c["high"]=max(c["high"],float(price)); c["low"]=min(c["low"],float(price)); c["close"]=float(price); c["volume"]+=delta
                    updated.append((token,sym,interval,c.copy()))
            # Batch cache writes per tick packet, one upsert per instrument/timeframe.
            for token,sym,interval,c in updated:
                import pandas as pd
                try: save_frame(token,sym,interval,pd.DataFrame([c]),source="websocket")
                except Exception as e:
                    with self.lock: self.error="candle cache write: "+str(e)[:150]
            with self.lock: self.last_message=now.isoformat()
        def on_close(ws,code,reason):
            with self.lock: self.connected=False; self.error=f"WebSocket closed ({code}): {reason}"
        def on_error(ws,code,reason):
            with self.lock: self.connected=False; self.error=f"WebSocket error ({code}): {reason}"
        ticker.on_connect=on_connect; ticker.on_ticks=on_ticks; ticker.on_close=on_close; ticker.on_error=on_error
        ticker.connect(threaded=True)
    def stop(self):
        with self.lock: t=self.ticker; self.ticker=None; self.connected=False; self.tokens=set()
        if t:
            try: t.close()
            except Exception: pass
    def status(self):
        with self.lock: return {"connected":self.connected,"subscribed_instruments":len(self.tokens),"last_tick_at":self.last_message,"error":self.error}
stream=LiveCandleStream()
