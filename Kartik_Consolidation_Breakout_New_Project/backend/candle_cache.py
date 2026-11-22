"""Persistent OHLCV cache for Kartik Algo. Configure DATA_DIR on durable hosting."""
import os, sqlite3, threading
from pathlib import Path
import pandas as pd

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "kartik_candles.sqlite3"
_db_lock = threading.RLock()


def _connect():
    con = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_db():
    with _db_lock, _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS candles (
            instrument_token INTEGER NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
            candle_time TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
            volume REAL DEFAULT 0, source TEXT DEFAULT 'historical',
            PRIMARY KEY(instrument_token, interval, candle_time))""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol ON candles(symbol, interval, candle_time)")
        con.execute("""CREATE TABLE IF NOT EXISTS cache_meta (
            instrument_token INTEGER NOT NULL, interval TEXT NOT NULL,
            symbol TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(instrument_token, interval))""")


def save_frame(token, symbol, interval, frame, source="historical"):
    if frame is None or frame.empty:
        return 0
    df = frame.copy()
    if "date" not in df.columns:
        return 0
    dates = pd.to_datetime(df["date"], errors="coerce")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    rows=[]
    for i, r in df.iterrows():
        dt=dates.loc[i]
        if pd.isna(dt): continue
        rows.append((int(token), str(symbol), str(interval), dt.strftime("%Y-%m-%d %H:%M:%S"),
          float(r.get("open",0)),float(r.get("high",0)),float(r.get("low",0)),float(r.get("close",0)),
          float(r.get("volume",0) or 0),str(source)))
    if not rows: return 0
    with _db_lock, _connect() as con:
        con.executemany("""INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(instrument_token,interval,candle_time) DO UPDATE SET
          symbol=excluded.symbol,open=excluded.open,high=excluded.high,low=excluded.low,
          close=excluded.close,volume=excluded.volume,source=excluded.source""", rows)
        con.execute("INSERT INTO cache_meta VALUES(?,?,?,datetime('now')) ON CONFLICT(instrument_token,interval) DO UPDATE SET symbol=excluded.symbol,updated_at=excluded.updated_at",(int(token),str(interval),str(symbol)))
    return len(rows)


def load_frame(token, interval):
    with _db_lock, _connect() as con:
        df=pd.read_sql_query("SELECT candle_time AS date,open,high,low,close,volume FROM candles WHERE instrument_token=? AND interval=? ORDER BY candle_time",con,params=(int(token),str(interval)))
    if not df.empty: df["date"]=pd.to_datetime(df["date"])
    return df


def cache_status():
    with _db_lock, _connect() as con:
        count=con.execute("SELECT COUNT(DISTINCT instrument_token) FROM candles").fetchone()[0]
        bars=con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        meta=con.execute("SELECT MAX(updated_at) FROM cache_meta").fetchone()[0]
    return {"db_path":str(DB_PATH),"cached_instruments":int(count),"cached_candles":int(bars),"last_cache_update":meta}

init_db()
