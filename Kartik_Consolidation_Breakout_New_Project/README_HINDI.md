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
