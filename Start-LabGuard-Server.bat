@echo off
setlocal
set "ROOT=%~dp0"
set "SERVER=%ROOT%labguard-server"
set "HOST=%LABGUARD_HOST%"
set "PORT=%LABGUARD_PORT%"
if not defined HOST set "HOST=0.0.0.0"
if not defined PORT set "PORT=8000"
if not exist "%SERVER%\.env" (
  echo Missing "%SERVER%\.env". Configure it from .env.example first.
  pause
  exit /b 1
)
if not exist "%SERVER%\.venv\Scripts\uvicorn.exe" (
  echo Server environment missing. See labguard-server\README.md.
  pause
  exit /b 1
)
start "LabGuard Server %HOST%:%PORT%" /D "%SERVER%" "%SERVER%\.venv\Scripts\uvicorn.exe" labguard_server.main:app --env-file .env --host %HOST% --port %PORT%
endlocal