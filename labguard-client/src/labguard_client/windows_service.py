from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from labguard_client.service_config import AgentConfig

if TYPE_CHECKING:
    from labguard_client.agent import AgentClient
    from labguard_client.identity import DeviceIdentity

SERVICE_NAME = "LabGuardAgent"
SERVICE_DISPLAY_NAME = "LabGuard Endpoint Agent"
SERVICE_DESCRIPTION = "Maintains the authenticated LabGuard device connection."
CONFIG_PATH = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "LabGuard" / "service.json"
_NATIVE_DLL_DIRECTORY_HANDLES = []


def _require_windows():
    if os.name != "nt":
        raise RuntimeError("Windows Service management is available only on Windows")
    try:
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise RuntimeError("Install the client Windows extra: pip install -e .[windows]") from exc
    return win32service, win32serviceutil


def prepare_service(server_url: str, state_dir: Path, telemetry_interval_seconds: float = 30.0,
                    software_inventory_interval_seconds: float = 6 * 60 * 60,
                    allow_insecure_dev: bool = False) -> Path:
    """Migrate existing user-DPAPI identity to machine DPAPI; refuse missing identity."""
    from labguard_client.identity import DeviceIdentity
    from labguard_client.windows_security import secure_state_directory

    config = AgentConfig(server_url=server_url, state_dir=state_dir.resolve(),
                         telemetry_interval_seconds=telemetry_interval_seconds,
                         software_inventory_interval_seconds=software_inventory_interval_seconds,
                         allow_insecure_dev=allow_insecure_dev)
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


def service_command(action: str, *, insecure_dev: bool = False) -> str:
    win32service, win32serviceutil = _require_windows()
    if action == "install":
        if not CONFIG_PATH.is_file():
            raise RuntimeError("Run labguard-agent service prepare first")
        config = AgentConfig.load(CONFIG_PATH)
        if config.server_url.startswith("http://") and not insecure_dev:
            raise RuntimeError("Service configuration enables HTTP; pass --insecure-dev explicitly to install it")
        if not (config.state_dir / "identity.json").is_file():
            raise RuntimeError("Service identity is missing; prepare again with the original enrolled identity")
        service_host = _service_host_executable(win32service)
        try:
            existing_status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        except Exception:
            existing_status = None
        else:
            if service_host is None:
                return f"Service {SERVICE_NAME} is already installed"
            if existing_status[1] != win32service.SERVICE_STOPPED:
                raise RuntimeError(f"Stop {SERVICE_NAME} before updating its Python Service host path")
            win32serviceutil.ChangeServiceConfig(
                "labguard_client.windows_service.LabGuardWindowsService", SERVICE_NAME,
                exeName=str(service_host), description=SERVICE_DESCRIPTION,
            )
            return f"Updated {SERVICE_NAME} Python Service host path; existing service account was preserved"
        install_options = dict(
            startType=win32service.SERVICE_AUTO_START,
            description=SERVICE_DESCRIPTION,
        )
        if service_host is not None:
            install_options["exeName"] = str(service_host)
        win32serviceutil.InstallService(
            "labguard_client.windows_service.LabGuardWindowsService", SERVICE_NAME, SERVICE_DISPLAY_NAME,
            **install_options,
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


def create_service_client(config: AgentConfig, identity: DeviceIdentity) -> AgentClient:
    """Build the service agent with the persisted transport policy."""
    # Keep the pywin32 service-class import lightweight. The full agent dependency
    # graph is loaded only after ServiceFramework.SvcRun reports SERVICE_RUNNING.
    from labguard_client.agent import AgentClient

    return AgentClient(config.server_url, identity, timeout=config.timeout,
                       telemetry_interval_seconds=config.telemetry_interval_seconds,
                       software_inventory_interval_seconds=config.software_inventory_interval_seconds,
                       allow_insecure_dev=config.allow_insecure_dev)


def _stage_venv_service_host(venv_root: Path, host_source: Path, python_dll: Path,
                             pywin32_dll_dir: Path, version_suffix: str) -> Path:
    """Stage pywin32's host where CPython detects the venv and bundle runtime DLLs."""
    scripts_dir = venv_root / "Scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    host_target = scripts_dir / "pythonservice.exe"
    shutil.copy2(host_source, host_target)
    for dll_name in (python_dll.name, f"pywintypes{version_suffix}.dll", f"pythoncom{version_suffix}.dll"):
        dll_source = python_dll if dll_name == python_dll.name else pywin32_dll_dir / dll_name
        if not dll_source.is_file():
            raise FileNotFoundError(f"Required pywin32 service runtime file is missing: {dll_source}")
        shutil.copy2(dll_source, scripts_dir / dll_name)
    return host_target


def _service_host_executable(win32service) -> Path | None:
    """Return a Scripts-hosted runtime only when service installation runs in a venv."""
    if Path(sys.prefix) == Path(sys.base_prefix):
        return None
    venv_root = Path(sys.prefix)
    host_candidates = (venv_root / "pythonservice.exe",
                       Path(win32service.__file__).resolve().parent / "pythonservice.exe")
    host_source = next((candidate for candidate in host_candidates if candidate.is_file()), None)
    if host_source is None:
        raise FileNotFoundError("Could not locate pywin32 pythonservice.exe in the active virtual environment")
    import win32api
    python_dll = Path(win32api.GetModuleFileName(sys.dllhandle))
    pywin32_dll_dir = Path(win32service.__file__).resolve().parent.parent / "pywin32_system32"
    version_suffix = f"{sys.version_info.major}{sys.version_info.minor}"
    return _stage_venv_service_host(venv_root, host_source, python_dll,
                                   pywin32_dll_dir, version_suffix)


def _configure_service_logging() -> logging.Logger:
    """Open the protected ProgramData log before loading config or identity."""
    log_path = CONFIG_PATH.parent / "labguard-agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("labguard_client")
    logger.setLevel(logging.INFO)
    resolved = str(log_path.resolve())
    if not any(getattr(handler, "baseFilename", None) == resolved for handler in logger.handlers):
        handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=4, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _log_service_runtime(logger: logging.Logger) -> None:
    try:
        import win32api
        python_dll = win32api.GetModuleFileName(sys.dllhandle)
    except (ImportError, AttributeError, OSError):
        python_dll = "unavailable"
    logger.info("Service runtime executable=%s prefix=%s base_prefix=%s exec_prefix=%s python_dll=%s cwd=%s programdata_set=%s",
                sys.executable, sys.prefix, sys.base_prefix, sys.exec_prefix, python_dll, os.getcwd(),
                bool(os.environ.get("PROGRAMDATA")))
    logger.info("Service Python import paths=%r", sys.path)


def _prepare_native_dll_search() -> None:
    """Expose the base Python runtime DLLs before importing native extensions."""
    runtime_dir = os.path.abspath(sys.base_prefix)
    python_api_dll = os.path.join(runtime_dir, "python3.dll")
    if not os.path.isfile(python_api_dll):
        raise FileNotFoundError(f"Python runtime API DLL is missing: {python_api_dll}")
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        raise RuntimeError("Windows DLL directory registration is unavailable")
    # Python 3.8+ uses this explicit search path for extension dependencies.
    # Retain the handle: closing it removes the directory from the process search path.
    handle = add_dll_directory(runtime_dir)
    _NATIVE_DLL_DIRECTORY_HANDLES.append(handle)
    logging.getLogger("labguard_client").info(
        "Registered Python native runtime DLL directory=%s", runtime_dir
    )


def _create_service_event_loop():
    """Create and install a signal-free Windows event loop in the service thread."""
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    return loop


def _signal_async_stop(loop, stop_event) -> None:
    if loop and stop_event and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            logging.getLogger("labguard_client").exception("Could not signal service event loop to stop")


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
            self._request_stop()

        def SvcShutdown(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=5000)
            self._request_stop()

        def _request_stop(self):
            self._stop_requested.set()
            _signal_async_stop(self._loop, self._async_stop)

        def SvcDoRun(self):
            logger = logging.getLogger("labguard_client")
            try:
                # ServiceFramework.SvcRun reports SERVICE_RUNNING before entering
                # SvcDoRun; all potentially slow imports and initialization follow.
                logger = _configure_service_logging()
                logger.info("Windows service execution entered")
                _log_service_runtime(logger)
                config = AgentConfig.load(CONFIG_PATH)
                logger.info("Service configuration loaded insecure_dev=%s state_dir=%s",
                            config.allow_insecure_dev, config.state_dir)
                _prepare_native_dll_search()
                from labguard_client.identity import DeviceIdentity
                identity = DeviceIdentity.load_existing(config.state_dir)
                if identity.protection_scope != "machine":
                    raise RuntimeError("Identity is not machine-DPAPI protected; run service prepare under the enrolling account")
                logger.info("Existing device identity loaded with machine DPAPI protection")
                self._loop = _create_service_event_loop()
                self._async_stop = asyncio.Event()
                if self._stop_requested.is_set():
                    self._async_stop.set()
                from labguard_client.software_management import (
                    is_administrator, running_as_local_system, running_in_service_session,
                )
                try:
                    import win32api
                    account = win32api.GetUserName()
                except (ImportError, OSError):
                    account = "unavailable"
                logger.info("Windows service started account=%s local_system=%s elevated=%s session_0=%s",
                            account, running_as_local_system(), is_administrator(), running_in_service_session())
                client = create_service_client(config, identity)
                logger.info("Starting authenticated agent connection loop")
                self._loop.run_until_complete(client.run_forever(self._async_stop))
            except Exception as exc:
                logger.exception("Windows service startup/runtime failed (%s)", type(exc).__name__)
                try:
                    servicemanager.LogErrorMsg(f"LabGuard Agent failed: {type(exc).__name__}")
                except Exception:
                    logger.exception("Could not write service failure to the Windows Event Log")
                raise
            finally:
                if self._loop:
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    self._loop.close()
                    asyncio.set_event_loop(None)
                logger.info("Windows service stopped")
