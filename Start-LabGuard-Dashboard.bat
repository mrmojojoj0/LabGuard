@echo off
setlocal
set "ROOT=%~dp0"
set "DASHBOARD=%ROOT%labguard-dashboard"
if not defined LABGUARD_DASHBOARD_HOST set "LABGUARD_DASHBOARD_HOST=127.0.0.1"
if not defined LABGUARD_DASHBOARD_PORT set "LABGUARD_DASHBOARD_PORT=5173"
if not defined LABGUARD_API_PROXY_TARGET set "LABGUARD_API_PROXY_TARGET=http://127.0.0.1:8000"
if not exist "%DASHBOARD%\node_modules\.bin\vite.cmd" (
  echo Dashboard dependencies missing. Run npm install in labguard-dashboard first.
  pause
  exit /b 1
)
start "LabGuard Dashboard %LABGUARD_DASHBOARD_HOST%:%LABGUARD_DASHBOARD_PORT%" /D "%DASHBOARD%" "%ComSpec%" /k "set LABGUARD_DASHBOARD_HOST=%LABGUARD_DASHBOARD_HOST%&& set LABGUARD_DASHBOARD_PORT=%LABGUARD_DASHBOARD_PORT%&& set LABGUARD_API_PROXY_TARGET=%LABGUARD_API_PROXY_TARGET%&& npm run dev -- --host %LABGUARD_DASHBOARD_HOST% --port %LABGUARD_DASHBOARD_PORT%"
endlocal