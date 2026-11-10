@echo off
setlocal

set "CLIENT_ROOT=C:\Users\sakin\Downloads\LabGuard\labguard-client"
set "PYTHON=%CLIENT_ROOT%\.venv\Scripts\python.exe"
set "SERVICE=LabGuardAgent"
set "LOG=C:\ProgramData\LabGuard\labguard-agent.log"

title LabGuard Service Restart

:: Check for Administrator privileges.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Requesting Administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

if not exist "%PYTHON%" (
    echo ERROR: Python environment not found:
    echo %PYTHON%
    pause
    exit /b 1
)

echo.
echo === LabGuard: stopping service ===
"%PYTHON%" -m labguard_client.cli service stop
if errorlevel 1 (
    echo WARNING: Stop command returned an error. Checking service state...
    sc.exe query "%SERVICE%"
)

echo.
echo === LabGuard: starting service ===
"%PYTHON%" -m labguard_client.cli service start
if errorlevel 1 (
    echo ERROR: Service start command failed.
    goto show_logs
)

echo.
echo === LabGuard: service status ===
sc.exe queryex "%SERVICE%"

:show_logs
echo.
echo === Latest LabGuard agent log entries ===
if exist "%LOG%" (
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 40"
) else (
    echo Log file not found: %LOG%
)

echo.
echo Restart check complete.
pause
