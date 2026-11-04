from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import threading
from pathlib import Path

from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity
from labguard_client.service_config import AgentConfig

SERVICE_NAME = "LabGuardAgent"
SERVICE_DISPLAY_NAME = "LabGuard Endpoint Agent"
SERVICE_DESCRIPTION = "Maintains the authenticated LabGuard device connection."
CONFIG_PATH = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "LabGuard" / "service.json"


def _require_windows():
    if os.name != "nt":
        raise RuntimeError("Windows Service management is available only on Windows")
    try:
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise RuntimeError("Install the client Windows extra: pip install -e .[windows]") from exc
    return win32service, win32serviceutil


def prepare_service(server_url: str, state_dir: Path, telemetry_interval_seconds: float = 30.0) -> Path:
    """Migrate existing user-DPAPI identity to machine DPAPI; refuse missing identity."""
    from labguard_client.windows_security import secure_state_directory

    config = AgentConfig(server_url=server_url, state_dir=state_dir.resolve(),
                         telemetry_interval_seconds=telemetry_interval_seconds)
    identity_path = state_dir / "identity.json"
    if not identity_path.is_file():
        raise FileNotFoundError(f"No existing device identity at {identity_path}; enroll and approve this device first")
    # Run under the Windows account that created any current-user DPAPI identity.
    identity = DeviceIdentity.load_existing(state_dir)
    secure_state_directory(state_dir)
    identity.protection_scope = "machine"
    identity._save()
    secure_state_directory(CONFIG_PATH.parent)
    config.write(CONFIG_PATH)
    logging.getLogger("labguard_client").info("Service configuration prepared; existing device identity preserved")
    return CONFIG_PATH


def service_command(action: str) -> str:
    win32service, win32serviceutil = _require_windows()
    if action == "install":
        if not CONFIG_PATH.is_file():
            raise RuntimeError("Run labguard-agent service prepare first")
        config = AgentConfig.load(CONFIG_PATH)
        if not (config.state_dir / "identity.json").is_file():
            raise RuntimeError("Service identity is missing; prepare again with the original enrolled identity")
        try:
            win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        except Exception:
            pass
        else:
            return f"Service {SERVICE_NAME} is already installed"
        win32serviceutil.InstallService(
            "labguard_client.windows_service.LabGuardWindowsService", SERVICE_NAME, SERVICE_DISPLAY_NAME,
            startType=win32service.SERVICE_AUTO_START,
            description=SERVICE_DESCRIPTION,
        )
        return f"Installed {SERVICE_NAME} (automatic start)"
    if action == "uninstall":
        try:
            win32serviceutil.StopService(SERVICE_NAME)
        except Exception:
            pass
        win32serviceutil.RemoveService(SERVICE_NAME)
        return f"Uninstalled {SERVICE_NAME}; identity/configuration were retained"
    if action == "start":
        win32serviceutil.StartService(SERVICE_NAME)
        return f"Started {SERVICE_NAME}"
    if action == "stop":
        win32serviceutil.StopService(SERVICE_NAME)
        return f"Stopped {SERVICE_NAME}"
    if action == "restart":
        try:
            win32serviceutil.StopService(SERVICE_NAME)
        except Exception:
            pass
        win32serviceutil.StartService(SERVICE_NAME)
        return f"Restarted {SERVICE_NAME}"
    if action == "status":
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        states = {win32service.SERVICE_STOPPED: "STOPPED", win32service.SERVICE_START_PENDING: "START_PENDING",
                  win32service.SERVICE_STOP_PENDING: "STOP_PENDING", win32service.SERVICE_RUNNING: "RUNNING",
                  win32service.SERVICE_CONTINUE_PENDING: "CONTINUE_PENDING", win32service.SERVICE_PAUSE_PENDING: "PAUSE_PENDING",
                  win32service.SERVICE_PAUSED: "PAUSED"}
        return f"{SERVICE_NAME}: {states.get(status[1], status[1])}"
    raise ValueError(f"Unknown service action: {action}")


if os.name == "nt":
    import servicemanager
    import win32service
    import win32serviceutil

    class LabGuardWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self._loop = None
            self._async_stop = None
            self._stop_requested = threading.Event()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=5000)
            self._stop_requested.set()
            if self._loop and self._async_stop:
                self._loop.call_soon_threadsafe(self._async_stop.set)

        def SvcDoRun(self):
            logger = logging.getLogger("labguard_client")
            try:
                config = AgentConfig.load(CONFIG_PATH)
                logger.setLevel(logging.INFO)
                if not logger.handlers:
                    handler = RotatingFileHandler(config.state_dir / "labguard-agent.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8")
                    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                    logger.addHandler(handler)
                identity = DeviceIdentity.load_existing(config.state_dir)
                if identity.protection_scope != "machine":
                    raise RuntimeError("Identity is not machine-DPAPI protected; run service prepare under the enrolling account")
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._async_stop = asyncio.Event()
                if self._stop_requested.is_set():
                    self._async_stop.set()
                self.ReportServiceStatus(win32service.SERVICE_RUNNING)
                logger.info("Windows service started")
                client = AgentClient(config.server_url, identity, timeout=config.timeout,
                                     telemetry_interval_seconds=config.telemetry_interval_seconds)
                self._loop.run_until_complete(client.run_forever(self._async_stop))
            except Exception as exc:
                logger.error("Windows service terminated with %s", type(exc).__name__)
                servicemanager.LogErrorMsg(f"LabGuard Agent failed: {type(exc).__name__}")
                raise
            finally:
                if self._loop:
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    self._loop.close()
                logger.info("Windows service stopped")
