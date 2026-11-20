@echo off
setlocal
cd /d "%~dp0"
title Kartik Algo Website
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
if not exist "zerodha_credentials.txt" (
  echo Please create zerodha_credentials.txt from zerodha_credentials.example.txt
  pause
  exit /b 1
)
set APP_PASSWORD=kartik-local-change-this
set SESSION_SECRET=local-dev-session-secret-change
set PUBLIC_BASE_URL=http://127.0.0.1:8000
set COOKIE_SECURE=false
start "Kartik Algo Website" cmd /k ""%~dp0.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8000
echo Local website password: kartik-local-change-this
echo Change APP_PASSWORD in run_windows.bat before sharing this computer.
pause
