@echo off
setlocal EnableExtensions

set "CLIENT_ROOT=%~dp0labguard-client"
set "PYTHON=%CLIENT_ROOT%\.venv\Scripts\python.exe"
set "SERVICE=LabGuardAgent"

title LabGuard Client Build and Restart

:: Service installation requires an elevated prompt.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
    exit /b
)

if not exist "%PYTHON%" (
    echo ERROR: Client Python environment not found:
    echo %PYTHON%
    goto fail
)

sc.exe query "%SERVICE%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Windows service %SERVICE% is not installed.
    echo Install it first using the existing LabGuard client setup.
    goto fail
)

pushd "%CLIENT_ROOT%" || goto fail

echo.
echo === Stopping LabGuard Agent ===
sc.exe stop "%SERVICE%"
for /l %%I in (1,1,30) do (
    sc.exe query "%SERVICE%" | findstr /c:"STOPPED" >nul
    if not errorlevel 1 goto service_stopped
    timeout /t 1 /nobreak >nul
)
echo ERROR: Service did not stop within 30 seconds.
goto fail_popd

:service_stopped
echo.
echo === Building client wheel ===
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

echo.
echo === Updating Windows service ===
"%PYTHON%" -m labguard_client.cli service install --insecure-dev
if errorlevel 1 goto fail_popd

echo.
echo === Starting LabGuard Agent ===
sc.exe start "%SERVICE%"
if errorlevel 1 goto fail_popd
timeout /t 5 /nobreak >nul
sc.exe queryex "%SERVICE%"

echo.
echo Build and restart completed. Existing device identity and service configuration were retained.
popd
pause
exit /b 0

:fail_popd
popd
:fail
echo.
echo Build or service restart failed. Review the error above before retrying.
pause
exit /b 1
