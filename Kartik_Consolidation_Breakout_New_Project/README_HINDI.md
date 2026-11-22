# Kartik Algo — Website + Scanner

## Website
- Home, Scanner, Reports, Settings tabs.
- Mobile responsive UI.
- Existing Consolidation Breakout scanner integrated into Scanner tab.
- Website password login.
- Zerodha OAuth callback returns to the public website.
- API key/secret should be configured as hosting Environment Variables.

## Free Render Hosting
1. Create a GitHub account and a NEW repository named `kartik-algo`.
2. Upload all files/folders from this project to that repository. Do not upload `zerodha_credentials.txt`, `.venv`, or local secrets.
3. Sign in to Render and choose New > Blueprint, then connect the GitHub repository. Render reads `render.yaml`.
4. During setup, enter values for `APP_PASSWORD`, `KITE_API_KEY`, `KITE_API_SECRET`. `SESSION_SECRET` is generated automatically.
5. After Render deploys, copy the website URL, e.g. `https://kartik-algo.onrender.com`.
6. In Render Environment, set `PUBLIC_BASE_URL` to that exact HTTPS URL and redeploy.
7. In Kite Connect developer console, set Redirect URL to:
   `https://YOUR-RENDER-SERVICE.onrender.com/api/zerodha/callback`
   Replace the domain with the exact Render URL. Save the Kite app settings.
8. Open website on mobile or computer, enter `APP_PASSWORD`, go to Settings, click Connect Zerodha, and authorize.
9. Open Scanner tab and run the scan.

## Local Windows Run
1. Copy `zerodha_credentials.example.txt` to `zerodha_credentials.txt` and fill API_KEY and API_SECRET.
2. Run `run_windows.bat`.
3. Local website opens at `http://127.0.0.1:8000`.
4. Local password is `kartik-local-change-this`; change it in `run_windows.bat` before using on a shared PC.

## Free-tier limitations
Render free web services sleep after 15 minutes with no inbound traffic; first request after sleep can take about one minute. Local filesystem is ephemeral and service can restart, so in-memory Zerodha login and active scan state are lost after restart. Use for personal testing, not unattended production scanning. Never place API secrets in GitHub.


## Mobile / iPhone use
- iPhone Safari और Android Chrome में केवल Render HTTPS URL खोलें: `https://YOUR-RENDER-SERVICE.onrender.com`.
- `localhost:8501` और `127.0.0.1:8000` केवल उसी कंप्यूटर के local development के लिए हैं; mobile पर इनका उपयोग न करें।
- Render पर `PUBLIC_BASE_URL` को exact public HTTPS service URL रखें। Kite Connect Redirect URL में उसी domain के साथ `/api/zerodha/callback` जोड़ें।
- Scanner UI Render वेबसाइट में ही मौजूद है; पुराने Streamlit `frontend/app.py` को Render deployment के लिए इस्तेमाल न करें।


## नई Scanner सुविधाएँ (Continuous + Mobile)

- Run Scanner करने पर चुने हुए timeframe के अगले candle-slot पर auto scan चलता है। Intraday slots 09:15 IST से align हैं (उदाहरण: 15-minute में 09:15, 09:30, 09:45...)। Daily/Weekly/Monthly के लिए अगला calendar interval 09:15 IST पर रखा गया है। NSE holidays की अलग calendar integration अभी नहीं है।
- Stop Scanner वर्तमान symbol का request पूरा होने के बाद बाकी symbols रोकता है और auto schedule भी cancel करता है।
- Download Scan CSV में हर scanned symbol शामिल है—Signal, No Setup या Error सहित। यह backend CSV endpoint से आता है, इसलिए mobile Safari पर भी Download/Save/Share विकल्प काम कर सकता है।
- Results में Symbol, Signal, Close, Distance, Volume Ratio आदि के Ascending/Descending sort controls हैं।
- Auto scan browser page खुला रहने पर चलता है; मोबाइल Safari background में page suspend कर सकता है। Free Render instance idle होने पर sleep कर सकता है, इसलिए लगातार 24x7 unattended scanner की guarantee नहीं है।

Deploy के लिए GitHub में `backend/main.py` और `frontend/index.html` को इस package के versions से replace करके commit करें। Render का Auto-Deploy पूरा होने के बाद वेबसाइट reload करें।


### Stock Chart & Scan Rule Details (latest update)
Scanner result table में किसी Stock के Symbol पर क्लिक करें। उसी scan timeframe का candle/volume chart खुलेगा; resistance, support, buy/breakout level, scanned candle और consolidation area chart पर mark होंगे। नीचे scan settings और rule checks दिखाई देंगे। `Close · Back to Results` दबाने या Escape करने पर पहले वाला scanner result view लौटेगा; scan दोबारा नहीं चलेगा।

## Fast Scanner v2 — Historical Cache + Zerodha WebSocket

- Pehli scan par har instrument/timeframe ka historical OHLCV SQLite cache mein save hota hai.
- Subsequent scans cache-first hain; same historical data ko dobara REST se fetch nahi kiya jata.
- Zerodha KiteTicker selected universe ko subscribe karta hai aur 5m/15m/60m/day candles locally aggregate karke cache update karta hai.
- Scanner status mein cache candle/instrument count aur WebSocket connection state dikhte hain.
- Cache database `DATA_DIR/kartik_candles.sqlite3` mein hai. Local Windows par project `data` folder default hai.
- Render par local filesystem deploy/restart par ephemeral ho sakta hai. Persistence ke liye Render persistent disk attach karke `DATA_DIR` ko disk mount path (e.g. `/var/data`) set karein. Persistent disk plan availability/billing Render account par depend karta hai.
- Kite Connect live WebSocket + historical data permissions active subscription/app mein honi chahiye. API access token daily expire hota hai; login ke baad stream start karein.
- WebSocket live candles current incomplete candle ko update karti hain; scanner existing strategy ke completed-candle rules ko maintain karta hai.
- First warm-up historical API rate limit ke karan slow ho sakta hai. Repeat scan local cache se significantly faster hoga; no fixed 5–8 second guarantee because it depends on machine, symbol universe, and strategy settings.


## Inside Open Close (Breakout Scanner में जोड़ी गई Strategy)

Scanner Configuration में Strategy dropdown से Consolidation Breakout, Inside Open Close, या Run Both चुनें। Inside Open Close के नियम: configurable maximum N के भीतर Mother Candle; उसके बाद न्यूनतम 3 consecutive candles के open और close Mother Candle के high-low range में; latest completed candle का close Mother High से ऊपर। Entry breakout candle high + buffer, SL breakout candle low - buffer, quantity risk amount / per-share risk (whole shares), आधी quantity target 1:3 और शेष target 1:6। Results/CSV में mother date/range, entry, stoploss, quantity और targets शामिल हैं।

ध्यान दें: इस ZIP का मौजूदा ऐप historical/live-candle आधारित **scanner signal** देता है। इस बदलाव में broker order execution, full trade lifecycle paper trading या strategy backtest engine नहीं जोड़ा गया है; वे अलग execution/backtesting modules की आवश्यकता रखते हैं। Live mode में वास्तविक order नहीं भेजे जाते।


## Inside Open Close Backtest (नया)

Scanner में Strategy `Inside Open Close` या `Run Both Strategies` चुनने पर अलग Backtest panel दिखेगा। इसमें Backtest From/To, Backtest Timeframe, Stock Group, Maximum Symbols और Request Delay चुनें। Backtest Zerodha Kite historical candles से चलता है; इसके लिए Zerodha session connected होना आवश्यक है। Inside Open Close की Minimum Inside Candles, Maximum N, Entry/Stop Buffer और Risk Amount वर्तमान strategy settings से लेता है। Target नियम 1:3 पर 50% quantity और 1:6 पर बाकी quantity हैं। Results में trades, win rate, net P&L और CSV export शामिल है।

Backtest OHLC candle simulation है; यदि एक candle में Stoploss और Target दोनों छूते हैं तो conservative रूप से Stoploss पहले माना जाता है। Intraday historical range Zerodha/Kite की उपलब्धता और limits पर निर्भर करती है। API या data errors को Backtest result में per-symbol दिखाया जाता है।
