@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "CLIENT_ROOT=%ROOT%labguard-client"
set "VENV=%CLIENT_ROOT%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "SERVICE=LabGuardAgent"
set "STATE_DIR=%ProgramData%\LabGuard"
set "IDENTITY=%STATE_DIR%\identity.json"
set "SERVICE_CONFIG=%STATE_DIR%\service.json"
set "SERVER_ADDRESS="
set "SERVER_URL="
set "TRANSPORT_FLAG="
set "SERVICE_EXISTS=0"
set "SERVICE_WAS_RUNNING=0"

title LabGuard Client Setup / Build / Restart

:: Service installation and machine-scope identity setup require elevation.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ComSpec -ArgumentList '/k', '""%~f0""' -Verb RunAs"
    exit /b
)

if not exist "%CLIENT_ROOT%\pyproject.toml" (
    echo ERROR: LabGuard client source was not found:
    echo %CLIENT_ROOT%
    goto fail
)

if not exist "%PYTHON%" (
    echo Python environment not found. Creating it with Python 3.12...
    py -3.12 -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Could not create the environment. Install Python 3.12 and enable the py launcher.
        goto fail
    )
)

if not exist "%PYTHON%" (
    echo ERROR: Python environment was not created:
    echo %PYTHON%
    goto fail
)

pushd "%CLIENT_ROOT%" || goto fail

echo.
echo === Installing client requirements ===
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto fail_popd
"%PYTHON%" -m pip install -e ".[windows]"
if errorlevel 1 goto fail_popd

if exist "%SERVICE_CONFIG%" (
    echo.
    echo Existing service configuration found. Reusing its server URL and transport settings.
) else (
    echo.
    echo No service configuration found. Enter the LabGuard server IP address or hostname.
    echo You can also enter a full URL such as http://192.168.1.10:8000
    set /p "SERVER_ADDRESS=Server address: "
    if not defined SERVER_ADDRESS (
        echo ERROR: A server address is required.
        goto fail_popd
    )

    if /i "!SERVER_ADDRESS:~0,7!"=="http://" (
        set "SERVER_URL=!SERVER_ADDRESS!"
    ) else if /i "!SERVER_ADDRESS:~0,8!"=="https://" (
        set "SERVER_URL=!SERVER_ADDRESS!"
    ) else (
        set "SERVER_URL=http://!SERVER_ADDRESS!:8000"
    )
    if /i "!SERVER_URL:~0,7!"=="http://" set "TRANSPORT_FLAG=--insecure-dev"
)

if exist "%SERVICE_CONFIG%" (
    set "SERVICE_EXISTS=1"
)

if exist "%IDENTITY%" (
    echo Existing device identity found. Keeping this device identity.
) else (
    if not defined SERVER_URL (
        echo Reading the saved server URL from the service configuration...
        for /f "usebackq delims=" %%U in (`"%PYTHON%" -c "import json,os; print(json.load(open(os.environ['PROGRAMDATA'] + r'\LabGuard\service.json', encoding='utf-8'))['server_url'])"`) do set "SERVER_URL=%%U"
    )
    if not defined SERVER_URL (
        echo ERROR: Could not read server_url from the service configuration.
        goto fail_popd
    )
    if /i "!SERVER_URL:~0,7!"=="http://" set "TRANSPORT_FLAG=--insecure-dev"
    echo.
    echo An enrollment code is required for this new device.
    set /p "ENROLLMENT_CODE=Enter the one-time enrollment code: "
    if not defined ENROLLMENT_CODE (
        echo ERROR: An enrollment code is required.
        goto fail_popd
    )
    echo.
    echo === Submitting device enrollment ===
    "%PYTHON%" -m labguard_client.cli enroll --server "!SERVER_URL!" --code "!ENROLLMENT_CODE!" !TRANSPORT_FLAG!
    if errorlevel 1 goto fail_popd
)

sc.exe query "%SERVICE%" >nul 2>&1
if not errorlevel 1 (
    set "SERVICE_EXISTS=1"
    sc.exe query "%SERVICE%" | findstr /c:"RUNNING" >nul
    if not errorlevel 1 set "SERVICE_WAS_RUNNING=1"
    echo.
    echo === Stopping existing LabGuard Agent ===
    sc.exe stop "%SERVICE%" >nul 2>&1
    for /l %%I in (1,1,30) do (
        sc.exe query "%SERVICE%" | findstr /c:"STOPPED" >nul
        if not errorlevel 1 goto service_stopped
        timeout /t 1 /nobreak >nul
    )
    echo ERROR: Existing service did not stop within 30 seconds.
    goto fail_popd
)

:service_stopped
echo.
echo === Building client wheel ===
if not exist "%CLIENT_ROOT%\dist" mkdir "%CLIENT_ROOT%\dist"
"%PYTHON%" -m pip wheel --no-deps --no-build-isolation --wheel-dir "%CLIENT_ROOT%\dist" "%CLIENT_ROOT%"
if errorlevel 1 goto fail_popd

set "WHEEL="
for /f "delims=" %%W in ('powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%CLIENT_ROOT%\dist' -Filter 'labguard_client-*.whl' ^| Sort-Object LastWriteTime -Descending ^| Select-Object -First 1 -ExpandProperty FullName"') do set "WHEEL=%%W"
if not defined WHEEL (
    echo ERROR: Build completed but no client wheel was found in:
    echo %CLIENT_ROOT%\dist
    goto fail_popd
)

echo.
echo === Installing %WHEEL% ===
"%PYTHON%" -m pip install --no-deps --force-reinstall "%WHEEL%"
if errorlevel 1 goto fail_popd

if not exist "%SERVICE_CONFIG%" (
    echo.
    echo === Preparing this device's Windows service configuration ===
    "%PYTHON%" -m labguard_client.cli service prepare --server "!SERVER_URL!" !TRANSPORT_FLAG!
    if errorlevel 1 goto fail_popd
)

echo.
echo === Installing or updating Windows service ===
"%PYTHON%" -m labguard_client.cli service install !TRANSPORT_FLAG!
if errorlevel 1 goto fail_popd

echo.
if not exist "%IDENTITY%" (
    echo ERROR: Device identity was not created during enrollment.
    goto fail_popd
)
echo A LabGuard administrator must approve this device before it connects.
echo Approve the pending device in the dashboard, then this script will start the agent.
pause

echo.
echo === Starting LabGuard Agent ===
sc.exe start "%SERVICE%"
if errorlevel 1 goto fail_popd
timeout /t 5 /nobreak >nul
sc.exe queryex "%SERVICE%"

echo.
echo Setup/build/restart completed. Device identity and service configuration are in %STATE_DIR%.
popd
pause
exit /b 0

:fail_popd
popd
:fail
echo.
echo Setup/build/restart failed. Review the error above before retrying.
pause
exit /b 1
