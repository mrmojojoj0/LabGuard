@echo off
setlocal
set "ROOT=%~dp0"
set "CLIENT=%ROOT%labguard-client"
set "PYTHON=%CLIENT%\.venv\Scripts\python.exe"
set "SERVER_URL=%LABGUARD_SERVER_URL%"
set "STATE_DIR=%LABGUARD_STATE_DIR%"
set "DEV_FLAG="
if not defined SERVER_URL set "SERVER_URL=http://127.0.0.1:8000"
if not defined STATE_DIR set "STATE_DIR=%PROGRAMDATA%\LabGuard"
if /I "%SERVER_URL:~0,7%"=="http://" (
  if not "%LABGUARD_ALLOW_INSECURE_DEV%"=="1" (
    echo Plain HTTP requires explicit development opt-in.
    echo Set LABGUARD_ALLOW_INSECURE_DEV=1 in this window, then retry.
    pause
    exit /b 1
  )
  set "DEV_FLAG=--insecure-dev"
)
if not exist "%PYTHON%" (
  echo Client environment missing. See labguard-client\README.md.
  pause
  exit /b 1
)
if /I "%~1"=="enroll" (
  "%PYTHON%" -m labguard_client.cli enroll --server "%SERVER_URL%" --state-dir "%STATE_DIR%" %DEV_FLAG%
  if errorlevel 1 pause
  exit /b
)
if not exist "%STATE_DIR%\identity.json" (
  echo No device identity exists. Run this launcher with the enroll argument first.
  echo Example: set LABGUARD_SERVER_URL=https://your-server-name:8000
  echo Then: Start-LabGuard-Client.bat enroll
  pause
  exit /b 1
)
"%PYTHON%" -m labguard_client.cli run --server "%SERVER_URL%" --state-dir "%STATE_DIR%" %DEV_FLAG%
if errorlevel 1 pause
endlocal