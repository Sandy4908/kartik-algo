import time
import streamlit as st
import pandas as pd
import requests

API="http://127.0.0.1:8000"
st.set_page_config(page_title="Kartik Algo",page_icon="📈",layout="wide")
st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 50% 0%,#153b27 0%,#07130d 55%)}
[data-testid="stHeader"]{background:transparent}
h1,h2,h3,p,label{color:#e8f3eb}
.login-wrap{max-width:650px;margin:9vh auto 0;background:linear-gradient(145deg,#10291b,#09170f);border:1px solid #315d40;border-radius:22px;padding:44px 48px;text-align:center;box-shadow:0 20px 60px #0007}
.brand{font-size:13px;letter-spacing:4px;color:#8fcaa0;font-weight:800}
.login-title{font-size:32px;font-weight:800;color:#f2fff4;margin:18px 0 8px}
.login-sub{font-size:14px;color:#a8c4af;margin-bottom:30px}
.stButton>button,.stLinkButton>a{background:#237447!important;color:white!important;border:1px solid #4b9565!important;border-radius:10px!important;font-weight:700!important}
[data-testid="stMetric"]{background:#10251a;border:1px solid #28543a;border-radius:12px;padding:12px}
</style>
""",unsafe_allow_html=True)

def get(path,timeout=8):
    r=requests.get(API+path,timeout=timeout);r.raise_for_status();return r.json()
def post(path,payload=None,timeout=15):
    r=requests.post(API+path,json=payload or {},timeout=timeout);r.raise_for_status();return r.json()

try:
    get("/api/health")
    connection=get("/api/zerodha/status")
except Exception:
    st.error("Backend चालू नहीं है। run_windows.bat चलाएँ।");st.stop()

if not connection.get("connected"):
    st.markdown('<div class="login-wrap"><div class="brand">KARTIK ALGO</div><div class="login-title">ZERODHA LOGIN</div><div class="login-sub">Secure account connection</div>',unsafe_allow_html=True)
    if connection.get("credentials_loaded"):
        try:
            url=get("/api/zerodha/login-url")["login_url"]
            st.link_button("CONNECT WITH ZERODHA",url,use_container_width=True)
        except Exception as e: st.error(f"Login link error: {e}")
    else:
        st.error("zerodha_credentials.txt file नहीं मिली। Project folder में file रखें और app restart करें।")
    st.markdown('</div>',unsafe_allow_html=True)
    st.stop()

a,b=st.columns([5,1])
with a:
    st.title("Kartik Consolidation Breakout")
    st.caption("ZERODHA CONNECTED")
with b:
    if st.button("Logout"):
        post("/api/zerodha/logout");st.rerun()

st.subheader("Scanner Configuration")
with st.form("scanner_settings"):
    c1,c2,c3=st.columns(3)
    with c1:
        timeframe=st.selectbox("Timeframe",["5 Minute","15 Minute","60 Minute","Daily","Weekly","Monthly"],index=3)
        universe=st.multiselect("Stock Group",["NIFTY 50 Stocks","NIFTY 500 Stocks","F&O Stocks"],default=["NIFTY 50 Stocks"])
    with c2:
        cmin=st.number_input("Minimum consolidation candles",min_value=1,max_value=500,value=10,step=1)
        cmax=st.number_input("Maximum consolidation candles",min_value=1,max_value=500,value=15,step=1)
    with c3:
        max_range=st.number_input("Maximum consolidation range (%)",0.5,15.0,3.5,0.5)
        near=st.number_input("Near breakout distance (%)",0.1,5.0,1.0,0.1)
    d1,d2,d3=st.columns(3)
    with d1: volmult=st.number_input("Volume multiple",1.0,5.0,1.5,0.1)
    with d2: volperiod=st.number_input("Average volume lookback",5,50,20)
    with d3: max_symbols=st.number_input("Maximum symbols (0 = all)",0,2000,0,50)
    delay=st.number_input("Request delay (seconds)",0.1,2.0,0.2,0.05)
    run=st.form_submit_button("RUN SCANNER",type="primary",use_container_width=True)

if run:
    if not universe: st.error("कम से कम एक Stock Group चुनें।")
    elif cmin>cmax: st.error("Minimum consolidation candles, Maximum consolidation candles से अधिक नहीं हो सकते।")
    else:
        has500="NIFTY 50 Stocks" in universe or "NIFTY 500 Stocks" in universe
        hasfo="F&O Stocks" in universe
        choice="NSE 500 + F&O" if has500 and hasfo else ("NSE 500 Only" if has500 else "F&O Only")
        interval_map={"5 Minute":"5minute","15 Minute":"15minute","60 Minute":"60minute","Daily":"day","Weekly":"week","Monthly":"month"}
        payload={"timeframe":interval_map[timeframe],"universe":choice,"consolidation_min":int(cmin),"consolidation_max":int(cmax),
            "max_range_pct":float(max_range),"near_pct":float(near),"volume_multiple":float(volmult),
            "volume_period":int(volperiod),"max_symbols":int(max_symbols),"request_delay":float(delay)}
        try:
            start_reply=post("/api/scanner/start",payload)
            st.session_state["scan_active"]=True
            st.session_state["active_scan_id"]=start_reply.get("scan_id")
            st.session_state.pop("last_scan_results",None)
        except Exception as e: st.error(f"Scanner start error: {e}")

if st.session_state.get("scan_active"):
    # Fresh placeholders ensure the previous run's table/status is never left on screen.
    status_box=st.empty();bar=st.progress(0);results_box=st.empty()
    results_box.empty()
    while True:
        try: state=get("/api/scanner/status")
        except Exception as e:
            status_box.error(f"Progress error: {e}");break
        expected_id=st.session_state.get("active_scan_id")
        if expected_id and state.get("scan_id") != expected_id:
            status_box.error("Scanner session बदल गई है। कृपया नया Scan शुरू करें।")
            st.session_state["scan_active"]=False
            break
        total=state.get("total",0);done=state.get("progress",0)
        bar.progress(min(100,int(done*100/total)) if total else 0)
        status_box.info(f"{state.get('timeframe','day')} | {done}/{total} stocks | Current: {state.get('current_symbol') or 'Preparing'} | Signals: {state.get('signals_count',0)} | Errors: {state.get('errors_count',0)}")
        frame=pd.DataFrame(state.get("signals",[]))
        if not frame.empty: results_box.dataframe(frame,use_container_width=True,hide_index=True)
        if state.get("error"):
            results_box.empty()
            bar.progress(min(100,int(done*100/total)) if total else 0)
            status_box.error(f"Scan रुक गया: {state['error']} | {done}/{total} stocks processed")
            st.session_state["scan_active"]=False
            break
        if state.get("done"):
            bar.progress(100)
            status_box.success(f"{state.get('timeframe','day')} scan complete — {state.get('signals_count',0)} signals from {total} symbols.")
            if frame.empty: st.warning("Scan complete हुआ, लेकिन कोई qualifying setup नहीं मिला।")
            else: st.download_button("Download CSV",frame.to_csv(index=False).encode("utf-8"),"kartik_breakout_signals.csv","text/csv")
            if state.get("errors"):
                with st.expander(f"API errors ({state['errors_count']})"):
                    st.dataframe(pd.DataFrame(state["errors"]),use_container_width=True,hide_index=True)
            st.session_state["scan_active"]=False;break
        time.sleep(2)
