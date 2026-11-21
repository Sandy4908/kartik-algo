import os
import csv
import io
import threading
import uuid
from datetime import datetime, date, time as dt_time, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from kiteconnect import KiteConnect

from backend.strategy import scan_symbol, normalize_ohlcv

IST = ZoneInfo("Asia/Kolkata")
app = FastAPI(title="Kartik Algo", version="2.0.0")

# In-memory session state: tokens are not written to disk.
_state = {
    "api_key": None,
    "api_secret": None,
    "access_token": None,
    "kite": None,
    "last_login": None,
    "scan_job": {"running": False, "done": False, "progress": 0, "total": 0,
                 "current_symbol": "", "signals": [], "scanned": [], "errors": [], "error": None,
                 "stop_requested": False, "stopped": False, "scan_date": None, "universe": None, "scan_id": None, "settings": None},
}
_lock = threading.Lock()

PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000").rstrip("/")
REDIRECT_URL = PUBLIC_BASE_URL + "/api/zerodha/callback"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
NIFTY500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
NIFTY50_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"


class Credentials(BaseModel):
    api_key: str = Field(min_length=4)
    api_secret: str = Field(min_length=4)


class ScanSettings(BaseModel):
    timeframe: str = Field(default="day", pattern="^(5minute|15minute|60minute|day|week|month)$")
    universe: str = "NSE 500 + F&O"
    consolidation_min: int = Field(default=10, ge=1, le=500)
    consolidation_max: int = Field(default=15, ge=1, le=500)
    max_range_pct: float = Field(default=3.0, gt=0, le=20)
    near_pct: float = Field(default=2.0, gt=0, le=10)
    volume_multiple: float = Field(default=1.5, ge=1, le=10)
    volume_period: int = Field(default=20, ge=5, le=60)
    max_symbols: int = Field(default=0, ge=0, le=2000)
    request_delay: float = Field(default=0.35, ge=0.1, le=3)



CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "zerodha_credentials.txt")

def _load_credentials_file():
    """Load credentials from hosting environment variables or local text file."""
    api_key = os.environ.get("KITE_API_KEY", "").strip()
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()
    if not (api_key and api_secret) and os.path.exists(CREDENTIALS_FILE):
        values = {}
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip().upper()] = value.strip().strip('"').strip("'")
        api_key = api_key or values.get("API_KEY", "")
        api_secret = api_secret or values.get("API_SECRET", "")
    if api_key and api_secret:
        _state["api_key"], _state["api_secret"] = api_key, api_secret
        return True
    return False


def _kite_for_key(api_key: str, access_token: Optional[str] = None):
    kite = KiteConnect(api_key=api_key)
    if access_token:
        kite.set_access_token(access_token)
    return kite


@app.on_event("startup")
def load_local_zerodha_credentials():
    _load_credentials_file()


@app.middleware("http")
async def app_auth_guard(request: Request, call_next):
    path = request.url.path
    public_paths = {"/", "/api/login", "/api/health", "/api/zerodha/callback"}
    if path in public_paths or path.startswith("/assets/"):
        return await call_next(request)
    if not request.session.get("authenticated"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Please login to Kartik Algo."}, status_code=401)
        return RedirectResponse("/", status_code=303)
    return await call_next(request)


# Register SessionMiddleware after @app.middleware so it wraps the auth guard.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "CHANGE-ME-" + os.urandom(24).hex()),
    https_only=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    same_site="lax",
)


@app.get("/", response_class=HTMLResponse)
def root():
    page = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "index.html")
    return FileResponse(page)


@app.post("/api/login")
async def app_login(request: Request):
    if not APP_PASSWORD:
        raise HTTPException(503, "Website password is not configured.")
    body = await request.json()
    supplied = str(body.get("password", ""))
    import hmac
    if not hmac.compare_digest(supplied, APP_PASSWORD):
        raise HTTPException(401, "Incorrect website password.")
    request.session["authenticated"] = True
    return {"ok": True}


@app.post("/api/logout")
def app_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/app/status")
def app_status():
    return {"app": "Kartik Algo",
            "zerodha_credentials_loaded": bool(_state["api_key"] and _state["api_secret"]),
            "zerodha_connected": bool(_state["kite"] and _state["access_token"]),
            "redirect_url": REDIRECT_URL}


@app.get("/assets/{asset_path:path}")
def assets(asset_path: str):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    target = os.path.abspath(os.path.join(base, asset_path))
    if not target.startswith(os.path.abspath(base) + os.sep):
        raise HTTPException(404, "Not found")
    if not os.path.isfile(target):
        raise HTTPException(404, "Not found")
    return FileResponse(target)


@app.get("/api/health")
def health():
    return {"status": "ok", "project": "Kartik Algo", "redirect_url": REDIRECT_URL}


@app.post("/api/zerodha/credentials")
def save_credentials(body: Credentials):
    with _lock:
        _state["api_key"] = body.api_key.strip()
        _state["api_secret"] = body.api_secret.strip()
        _state["access_token"] = None
        _state["kite"] = None
        _state["last_login"] = None
    return {"ok": True, "message": "Credentials stored in backend memory for this run.", "redirect_url": REDIRECT_URL}


@app.get("/api/zerodha/login-url")
def login_url():
    if not _state["api_key"]:
        raise HTTPException(400, "First save your Kite API Key and API Secret.")
    kite = _kite_for_key(_state["api_key"])
    return {"login_url": kite.login_url(), "redirect_url": REDIRECT_URL}


@app.get("/api/zerodha/callback", response_class=HTMLResponse)
def zerodha_callback(
    request_token: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
):
    if status == "cancelled" or not request_token:
        return HTMLResponse("""
        <html><body style="font-family:Arial;background:#07130d;color:#fff;padding:35px">
        <h2>Zerodha login was cancelled or request_token was missing.</h2>
        <p>Return to Kartik Consolidation Breakout Algo and try again.</p>
        </body></html>""", status_code=400)
    if not _state["api_key"] or not _state["api_secret"]:
        return HTMLResponse("""
        <html><body style="font-family:Arial;background:#07130d;color:#fff;padding:35px">
        <h2>Credentials missing</h2><p>Return to the app, save API Key and API Secret, then login again.</p>
        </body></html>""", status_code=400)
    try:
        kite = _kite_for_key(_state["api_key"])
        data = kite.generate_session(request_token, api_secret=_state["api_secret"])
        kite.set_access_token(data["access_token"])
        with _lock:
            _state["access_token"] = data["access_token"]
            _state["kite"] = kite
            _state["last_login"] = datetime.now(IST).isoformat()
        # Automatically return to the Streamlit dashboard after successful login.
        return RedirectResponse(
            url=PUBLIC_BASE_URL + "/?zerodha=connected",
            status_code=303,
        )
    except Exception as exc:
        return HTMLResponse(
            "<html><body style='font-family:Arial;background:#07130d;color:#fff;padding:35px'>"
            "<h2>Token exchange failed</h2><p>" + str(exc).replace("<", "&lt;") + "</p>"
            "<p>Return to the app and retry Zerodha login.</p></body></html>",
            status_code=400,
        )


@app.get("/api/zerodha/status")
def zerodha_status():
    return {
        "connected": bool(_state["kite"] and _state["access_token"]),
        "last_login": _state["last_login"],
        "redirect_url": REDIRECT_URL,
        "credentials_loaded": bool(_state["api_key"] and _state["api_secret"]),
    }


@app.post("/api/zerodha/logout")
def zerodha_logout():
    with _lock:
        _state["access_token"] = None
        _state["kite"] = None
        _state["last_login"] = None
    return {"ok": True}


def _get_kite():
    if not _state["kite"]:
        raise HTTPException(401, "Zerodha is not connected. Complete Kite login first.")
    return _state["kite"]


def _nifty500_symbols():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*",
        "Referer": "https://www.niftyindices.com/",
    }
    resp = requests.get(NIFTY500_URL, headers=headers, timeout=25)
    resp.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(resp.content))
    col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    if not col:
        raise RuntimeError("Nifty 500 constituent file did not contain a Symbol column.")
    return set(df[col].astype(str).str.strip().str.upper())


def _nifty50_symbols():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*",
        "Referer": "https://www.niftyindices.com/",
    }
    resp = requests.get(NIFTY50_URL, headers=headers, timeout=25)
    resp.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(resp.content))
    col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    if not col:
        raise RuntimeError("Nifty 50 constituent file did not contain a Symbol column.")
    return set(df[col].astype(str).str.strip().str.upper())


def _fetch_universe(kite, choice):
    nse = pd.DataFrame(kite.instruments("NSE"))
    if nse.empty:
        return []
    eq = nse[(nse["instrument_type"] == "EQ") & nse["tradingsymbol"].notna()].copy()
    eq["symbol"] = eq["tradingsymbol"].astype(str).str.upper()
    token_map = dict(zip(eq["symbol"], eq["instrument_token"]))

    n500 = _nifty500_symbols()
    n50 = _nifty50_symbols()
    nfo = pd.DataFrame(kite.instruments("NFO"))
    fo = set()
    if not nfo.empty and {"instrument_type", "name"}.issubset(nfo.columns):
        fo = set(nfo.loc[nfo["instrument_type"] == "FUT", "name"].dropna().astype(str).str.upper())

    groups = {
        "NSE 50 Only": n50,
        "NSE 500 Only": n500,
        "F&O Only": fo,
        "NSE 50 + NSE 500": n50 | n500,
        "NSE 50 + F&O": n50 | fo,
        "NSE 500 + F&O": n500 | fo,
        "NSE 50 + NSE 500 + F&O": n50 | n500 | fo,
    }
    selected = groups.get(choice, n500 | fo)

    return [{"symbol": sym, "instrument_token": int(token_map[sym])}
            for sym in sorted(selected) if sym in token_map]



def _scan_worker(settings: ScanSettings):
    job = _state["scan_job"]
    try:
        kite = _get_kite()
        universe = _fetch_universe(kite, settings.universe)
        if settings.max_symbols:
            universe = universe[:settings.max_symbols]
        if not universe:
            raise RuntimeError("No matching NSE equity instruments found in selected universe.")
        now = datetime.now(IST)
        interval = settings.timeframe
        if interval in ("day", "week", "month"):
            last_completed = now.date() if now.time() >= dt_time(15, 30) else now.date() - timedelta(days=1)
            if interval == "day":
                history_days = max(100, settings.consolidation_max * 2 + settings.volume_period * 2 + 30)
            elif interval == "week":
                history_days = max(730, (settings.consolidation_max + settings.volume_period + 10) * 7)
            else:
                history_days = max(1825, (settings.consolidation_max + settings.volume_period + 10) * 31)
            start_dt = datetime.combine(last_completed - timedelta(days=history_days), dt_time.min)
            end_dt = datetime.combine(last_completed, dt_time.max)
            source_interval = "day"
        else:
            # Intraday candles: fetch a bounded recent window and exclude the still-forming candle.
            history_days = {"5minute": 60, "15minute": 180, "60minute": 365}[interval]
            start_dt = datetime.combine(now.date() - timedelta(days=history_days), dt_time.min)
            end_dt = now.replace(tzinfo=None)
            last_completed = now.date()
            source_interval = interval
        with _lock:
            job.update({"running": True, "done": False, "progress": 0, "total": len(universe),
                        "current_symbol": "", "signals": [], "scanned": [], "errors": [], "error": None,
                        "stopped": False, "scan_date": str(last_completed), "universe": settings.universe,
                        "timeframe": settings.timeframe, "settings": settings.model_dump()})
        import time
        for count, item in enumerate(universe, 1):
            with _lock:
                if job.get("stop_requested"):
                    job["stopped"] = True
                    break
                job["current_symbol"] = item["symbol"]
            scan_record = {"symbol": item["symbol"], "scan_status": "No Setup"}
            try:
                hist = kite.historical_data(item["instrument_token"],
                    start_dt, end_dt, interval=source_interval, continuous=False, oi=False)
                df = normalize_ohlcv(pd.DataFrame(hist))
                if not df.empty:
                    if interval in ("day", "week", "month"):
                        df = df[df["date"].dt.date <= last_completed].reset_index(drop=True)
                        if interval in ("week", "month"):
                            # Kite has no native weekly/monthly interval; aggregate completed
                            # daily candles locally and discard the currently-forming period.
                            dated = df.copy()
                            if dated["date"].dt.tz is not None:
                                dated["date"] = dated["date"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
                            dated = dated.set_index("date")
                            rule = "W-FRI" if interval == "week" else "M"
                            aggregated = dated.resample(rule, label="right", closed="right").agg({
                                "open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"
                            }).dropna(subset=["open", "high", "low", "close"]).reset_index()
                            aggregated = aggregated[aggregated["date"].dt.date <= last_completed]
                            df = normalize_ohlcv(aggregated)
                    else:
                        # Kite timestamps intraday candles at their opening time.
                        candle_minutes = {"5minute": 5, "15minute": 15, "60minute": 60}[interval]
                        dates = df["date"]
                        if dates.dt.tz is not None:
                            dates = dates.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
                        now_local = now.replace(tzinfo=None)
                        df = df[(dates + pd.to_timedelta(candle_minutes, unit="m")) <= now_local].reset_index(drop=True)
                    signal = scan_symbol(df, symbol=item["symbol"],
                        consolidation_min=settings.consolidation_min,
                        consolidation_max=settings.consolidation_max,
                        max_range_pct=settings.max_range_pct, near_pct=settings.near_pct,
                        volume_multiple=settings.volume_multiple, volume_period=settings.volume_period)
                    if signal:
                        scan_record.update(signal)
                        scan_record["scan_status"] = "Signal"
                        with _lock:
                            job["signals"].append(signal)
            except Exception as exc:
                scan_record["scan_status"] = "Error"
                scan_record["error"] = str(exc)[:200]
                with _lock:
                    job["errors"].append({"symbol": item["symbol"], "error": str(exc)[:200]})
            with _lock:
                job["scanned"].append(scan_record)
                job["progress"] = count
                should_stop = job.get("stop_requested", False)
            if should_stop:
                with _lock:
                    job["stopped"] = True
                break
            time.sleep(settings.request_delay)
        with _lock:
            job["signals"].sort(key=lambda x: (
                {"Breakout Confirmed": 0, "Near Breakout": 1, "Consolidation Forming": 2}.get(x["signal"], 3),
                x.get("distance_to_resistance_pct", 999)))
            job["running"] = False
            job["done"] = True
            job["current_symbol"] = ""
    except Exception as exc:
        with _lock:
            job["running"] = False
            job["done"] = True
            job["error"] = str(exc)


@app.post("/api/scanner/start")
def start_scan(settings: ScanSettings):
    _get_kite()
    if settings.consolidation_min > settings.consolidation_max:
        raise HTTPException(422, "Consolidation minimum cannot exceed maximum.")
    new_scan_id = str(uuid.uuid4())
    with _lock:
        if _state["scan_job"].get("running"):
            raise HTTPException(409, "A scanner job is already running. Wait for it to finish.")
        # Hard reset: no signal, error, counter or progress from the previous scan survives.
        _state["scan_job"].clear()
        _state["scan_job"].update({
            "running": True, "done": False, "progress": 0, "total": 0,
            "current_symbol": "Preparing stock universe...", "signals": [], "scanned": [],
            "errors": [], "error": None, "stop_requested": False, "stopped": False, "scan_date": None,
            "universe": settings.universe, "timeframe": settings.timeframe, "settings": settings.model_dump(),
            "scan_id": new_scan_id
        })
    threading.Thread(target=_scan_worker, args=(settings,), daemon=True).start()
    return {"ok": True, "scan_id": new_scan_id, "message": "New scanner run started; previous results cleared."}


@app.get("/api/scanner/status")
def scan_status():
    with _lock:
        j = _state["scan_job"]
        return {"running": j["running"], "done": j["done"], "progress": j["progress"],
            "total": j["total"], "current_symbol": j["current_symbol"],
            "signals_count": len(j["signals"]), "signals": list(j["signals"]),
            "errors_count": len(j["errors"]), "errors": list(j["errors"][-100:]),
            "scanned_count": len(j.get("scanned", [])),
            "stopped": j.get("stopped", False), "error": j["error"], "scan_date": j["scan_date"], "universe": j["universe"],
            "timeframe": j.get("timeframe", "day"), "scan_id": j.get("scan_id")}


@app.post("/api/scanner/stop")
def stop_scan():
    with _lock:
        job = _state["scan_job"]
        if not job.get("running"):
            return {"ok": True, "running": False, "message": "Scanner is not running."}
        job["stop_requested"] = True
        return {"ok": True, "running": True, "message": "Stop requested; current symbol will finish and remaining symbols will be skipped."}


@app.get("/api/scanner/csv")
def download_scan_csv():
    with _lock:
        rows = list(_state["scan_job"].get("scanned", []))
        scan_id = _state["scan_job"].get("scan_id") or "latest"
    columns = ["symbol", "scan_status", "signal", "date", "close", "resistance", "support",
               "range_pct", "distance_to_resistance_pct", "consolidation_candles", "volume",
               "average_volume", "volume_ratio", "breakout_candle_high", "buy_trigger", "note", "error"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    data = "\ufeff" + output.getvalue()
    filename = f"kartik_algo_scan_{scan_id[:8]}.csv"
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.get("/api/scanner/chart")
def scanner_chart(symbol: str = Query(min_length=1, max_length=30)):
    """Return the chart and exact consolidation conditions for a stock in the latest scan."""
    kite = _get_kite()
    symbol = symbol.strip().upper()
    with _lock:
        job = dict(_state["scan_job"])
        settings_data = dict(job.get("settings") or {})
        timeframe = job.get("timeframe", settings_data.get("timeframe", "day"))
        signal_row = next((dict(x) for x in job.get("signals", []) if x.get("symbol", "").upper() == symbol), None)
    if not settings_data:
        raise HTTPException(409, "Run the scanner first; chart conditions are saved with each scan.")
    # Resolve the symbol to its NSE equity token.
    instruments = pd.DataFrame(kite.instruments("NSE"))
    found = instruments[(instruments.get("tradingsymbol", pd.Series(dtype=str)).astype(str).str.upper() == symbol) &
                        (instruments.get("instrument_type", pd.Series(dtype=str)).astype(str) == "EQ")]
    if found.empty:
        raise HTTPException(404, f"NSE equity instrument not found for {symbol}.")
    token = int(found.iloc[0]["instrument_token"])
    now = datetime.now(IST)
    interval = timeframe
    if interval in ("day", "week", "month"):
        last_completed = now.date() if now.time() >= dt_time(15, 30) else now.date() - timedelta(days=1)
        cmax = int(settings_data.get("consolidation_max", 15))
        vperiod = int(settings_data.get("volume_period", 20))
        if interval == "day":
            history_days = max(100, cmax * 2 + vperiod * 2 + 30)
        elif interval == "week":
            history_days = max(730, (cmax + vperiod + 10) * 7)
        else:
            history_days = max(1825, (cmax + vperiod + 10) * 31)
        start_dt = datetime.combine(last_completed - timedelta(days=history_days), dt_time.min)
        end_dt = datetime.combine(last_completed, dt_time.max)
        source_interval = "day"
    else:
        days = {"5minute": 60, "15minute": 180, "60minute": 365}[interval]
        start_dt = datetime.combine(now.date() - timedelta(days=days), dt_time.min)
        end_dt = now.replace(tzinfo=None)
        last_completed = now.date()
        source_interval = interval
    try:
        raw = kite.historical_data(token, start_dt, end_dt, interval=source_interval, continuous=False, oi=False)
        df = normalize_ohlcv(pd.DataFrame(raw))
        if interval in ("day", "week", "month"):
            df = df[df["date"].dt.date <= last_completed].reset_index(drop=True)
            if interval in ("week", "month"):
                dated = df.copy()
                if dated["date"].dt.tz is not None:
                    dated["date"] = dated["date"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
                dated = dated.set_index("date")
                rule = "W-FRI" if interval == "week" else "M"
                df = dated.resample(rule, label="right", closed="right").agg({
                    "open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"
                }).dropna(subset=["open","high","low","close"]).reset_index()
                df = normalize_ohlcv(df)
                df = df[df["date"].dt.date <= last_completed].reset_index(drop=True)
        else:
            dates = df["date"]
            if dates.dt.tz is not None:
                dates = dates.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
            minutes = {"5minute":5,"15minute":15,"60minute":60}[interval]
            df = df[(dates + pd.to_timedelta(minutes, unit="m")) <= now.replace(tzinfo=None)].reset_index(drop=True)
        result = scan_symbol(df, symbol=symbol, consolidation_min=int(settings_data.get("consolidation_min",10)),
            consolidation_max=int(settings_data.get("consolidation_max",15)),
            max_range_pct=float(settings_data.get("max_range_pct",3.5)),
            near_pct=float(settings_data.get("near_pct",1)),
            volume_multiple=float(settings_data.get("volume_multiple",1.5)),
            volume_period=int(settings_data.get("volume_period",20)))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Chart data could not be fetched from Zerodha: " + str(exc)[:180])
    if df.empty:
        raise HTTPException(404, "No candle history returned for this symbol/timeframe.")
    # Keep chart lightweight on mobile; condition calculation uses the full available series.
    chart_df = df.tail(min(650, max(150, int(settings_data.get("consolidation_max", 15)) + 50))).copy().reset_index(drop=True)
    candles = [{"time": row["date"].isoformat(), "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else None}
               for _, row in chart_df.iterrows()]
    # Prefer the exact signal snapshot saved by the scanner; do not silently
    # replace it with a later candle if the user opens the chart minutes later.
    result = signal_row or result or {}
    n = int(result.get("consolidation_candles") or settings_data.get("consolidation_min",10))
    close = float(result.get("close") or chart_df.iloc[-1]["close"])
    resistance = result.get("resistance")
    support = result.get("support")
    volume_ratio = result.get("volume_ratio")
    range_pct = result.get("range_pct")
    near_pct = float(settings_data.get("near_pct",1))
    max_range = float(settings_data.get("max_range_pct",3.5))
    vol_multiple = float(settings_data.get("volume_multiple",1.5))
    distance = result.get("distance_to_resistance_pct")
    conditions = [
        {"name":"Consolidation candle count", "actual":n, "rule":f"{settings_data.get('consolidation_min',10)} to {settings_data.get('consolidation_max',15)} candles", "passed":settings_data.get('consolidation_min',10)<=n<=settings_data.get('consolidation_max',15)},
        {"name":"Consolidation range", "actual":f"{range_pct}%", "rule":f"≤ {max_range}%", "passed":range_pct is not None and float(range_pct)<=max_range},
        {"name":"Resistance / consolidation high", "actual":resistance, "rule":"Close above this level for breakout", "passed":resistance is not None},
        {"name":"Support / consolidation low", "actual":support, "rule":"Lowest low in consolidation window", "passed":support is not None},
        {"name":"Close vs resistance", "actual":close, "rule":f"Breakout: close > {resistance}; Near: within {near_pct}% below", "passed":resistance is not None and (close>float(resistance) or (distance is not None and 0<=float(distance)<=near_pct))},
        {"name":"Volume confirmation", "actual":volume_ratio, "rule":f"Volume ratio ≥ {vol_multiple}x for confirmed breakout", "passed":volume_ratio is not None and float(volume_ratio)>=vol_multiple},
        {"name":"Signal classification", "actual":result.get("signal", "No signal"), "rule":result.get("note", "Recalculated from latest completed candle"), "passed":bool(result)},
    ]
    return {"symbol":symbol,"timeframe":timeframe,"candles":candles,"conditions":conditions,
            "signal_date":result.get("date"), "signal":result.get("signal","No signal"),"note":result.get("note",""),
            "consolidation_candles":n,"resistance":resistance,"support":support,
            "buy_trigger":result.get("buy_trigger"),"breakout_candle_high":result.get("breakout_candle_high"),
            "range_pct":range_pct,"distance_to_resistance_pct":distance,"volume_ratio":volume_ratio,
            "scan_settings":settings_data}


@app.post("/api/scanner/run")
def run_scan(settings: ScanSettings):
    kite = _get_kite()
    if settings.consolidation_min > settings.consolidation_max:
        raise HTTPException(422, "Consolidation minimum cannot exceed maximum.")
    try:
        universe = _fetch_universe(kite, settings.universe)
    except Exception as exc:
        raise HTTPException(502, f"Could not build NSE 500 + F&O universe: {exc}")
    if settings.max_symbols:
        universe = universe[:settings.max_symbols]
    if not universe:
        raise HTTPException(404, "No matching NSE equity instruments found in the selected universe.")

    now = datetime.now(IST)
    last_completed = now.date() if now.time() >= dt_time(15, 30) else now.date() - timedelta(days=1)
    start = last_completed - timedelta(days=100)
    results, errors = [], []
    for item in universe:
        try:
            hist = kite.historical_data(
                instrument_token=item["instrument_token"],
                from_date=datetime.combine(start, dt_time.min),
                to_date=datetime.combine(last_completed, dt_time.max),
                interval="day",
                continuous=False,
                oi=False,
            )
            df = normalize_ohlcv(pd.DataFrame(hist))
            if not df.empty:
                df = df[df["date"].dt.date <= last_completed].reset_index(drop=True)
                result = scan_symbol(
                    df,
                    symbol=item["symbol"],
                    consolidation_min=settings.consolidation_min,
                    consolidation_max=settings.consolidation_max,
                    max_range_pct=settings.max_range_pct,
                    near_pct=settings.near_pct,
                    volume_multiple=settings.volume_multiple,
                    volume_period=settings.volume_period,
                )
                if result:
                    results.append(result)
        except Exception as exc:
            errors.append({"symbol": item["symbol"], "error": str(exc)[:200]})
        import time
        time.sleep(settings.request_delay)

    results.sort(key=lambda x: (
        {"Breakout Confirmed": 0, "Near Breakout": 1, "Consolidation Forming": 2}.get(x["signal"], 3),
        x.get("distance_to_resistance_pct", 999)
    ))
    return {
        "scan_date": str(last_completed),
        "universe": settings.universe,
        "symbols_requested": len(universe),
        "signals_found": len(results),
        "signals": results,
        "errors_count": len(errors),
        "errors": errors[:100],
        "entry_rule": "After Breakout Confirmed, trigger buy only when market price moves above breakout_candle_high. No orders are placed.",
    }
