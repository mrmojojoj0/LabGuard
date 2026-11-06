from datetime import UTC, datetime, timedelta
import asyncio
import json
import sys
import threading
import types
from uuid import uuid4

import pytest

from labguard_client.software_management import (
    PackageManagerUnavailable, SoftwareJobOffer, UnsupportedExecutionContext,
    build_command, discover_chocolatey, discover_winget, execute_package_job, is_administrator,
)
from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity
from labguard_client.software_management import PackageResult


def offer_payload(**overrides):
    value = {
        "job_id": str(uuid4()), "action": "INSTALL", "package_id": "Vendor.App",
        "package_manager": "WINGET", "version": None, "installation_scope": "MACHINE",
        "source": "WINGET_COMMUNITY", "source_url": None,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "timeout_seconds": 60,
    }
    value.update(overrides)
    return value


def offer(**overrides):
    return SoftwareJobOffer.parse(offer_payload(**overrides))


def test_job_offer_validation_and_fixed_argument_vector():
    parsed = offer()
    command = build_command(parsed, r"C:\Program Files\WindowsApps\winget.exe")
    assert command[:4] == [r"C:\Program Files\WindowsApps\winget.exe", "install", "--id", "Vendor.App"]
    assert "--exact" in command and "--source" in command and "--silent" in command
    with pytest.raises(ValueError):
        offer(package_id="Vendor.App;calc.exe")
    with pytest.raises(ValueError):
        offer(source="arbitrary")


def test_package_manager_discovery_uses_known_paths_without_path(tmp_path):
    candidate = tmp_path / "Microsoft" / "WindowsApps" / "winget.exe"
    candidate.parent.mkdir(parents=True)
    candidate.touch()
    winget = discover_winget(which=lambda _name: None, environ={"LOCALAPPDATA": str(tmp_path)})
    assert winget.endswith("WindowsApps\\winget.exe")
    with pytest.raises(PackageManagerUnavailable):
        discover_chocolatey(which=lambda _name: None, environ={"ProgramData": r"Z:\missing"})


def test_winget_execution_can_find_machine_registered_app_installer(tmp_path):
    executable = tmp_path / "Apps" / "WindowsApps" / "Microsoft.DesktopAppInstaller_1.0_x64__8wekyb3d8bbwe" / "winget.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    calls = []

    class Process:
        def __init__(self, args, **_kwargs):
            calls.append(args)
        def poll(self):
            return 0
        def wait(self, **_kwargs):
            return 0

    result = execute_package_job(offer(), local_system=True, administrator=True, service_context=True,
        environ={"ProgramFiles": str(tmp_path / "Apps")}, popen=Process)
    assert result.returncode == 0
    assert calls[0][0] == str(executable)


def test_service_context_rejects_interactive_user_job_and_unprivileged_machine_job():
    with pytest.raises(UnsupportedExecutionContext, match="user_scope"):
        execute_package_job(offer(installation_scope="USER"), local_system=True,
            administrator=True, which=lambda _name: None)
    with pytest.raises(UnsupportedExecutionContext, match="user_scope"):
        execute_package_job(offer(installation_scope="USER"), local_system=False,
            administrator=True, service_context=True, which=lambda _name: None)
    with pytest.raises(UnsupportedExecutionContext, match="privileged_service_unavailable"):
        execute_package_job(offer(), local_system=False, administrator=True,
            service_context=False, which=lambda _name: None)
    with pytest.raises(UnsupportedExecutionContext, match="administrator"):
        execute_package_job(offer(), local_system=False, administrator=False,
            service_context=True, which=lambda _name: None)


def test_local_system_detection_uses_supported_pywin32_sid_conversion(monkeypatch):
    import labguard_client.software_management as management

    monkeypatch.setattr(management.os, "name", "nt")
    current_sid = object()
    system_sid = object()
    fake_security = types.SimpleNamespace(
        OpenProcessToken=lambda _process, _access: "token",
        GetTokenInformation=lambda _token, _kind: (current_sid, 0),
        TokenUser=1,
        WinLocalSystemSid=5,
        CreateWellKnownSid=lambda _kind, _domain: system_sid,
        ConvertSidToStringSid=lambda sid: {current_sid: "S-1-5-18", system_sid: "s-1-5-18"}[sid],
    )
    monkeypatch.setitem(sys.modules, "win32api", types.SimpleNamespace(GetCurrentProcess=lambda: "process"))
    monkeypatch.setitem(sys.modules, "win32con", types.SimpleNamespace(TOKEN_QUERY=8))
    monkeypatch.setitem(sys.modules, "win32security", fake_security)

    assert management.running_as_local_system() is True

    fake_security.ConvertSidToStringSid = lambda sid: "S-1-5-21-user" if sid is current_sid else "S-1-5-18"
    assert management.running_as_local_system() is False


def test_operation_calls_mocked_manager_without_shell_and_sanitizes_output():
    calls = []

    class Process:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))
            kwargs["stdout"].write(b"token=supersecret installed successfully\n")
        def poll(self):
            return 0
        def wait(self, **_kwargs):
            return 0

    result = execute_package_job(offer(), local_system=True, administrator=True, service_context=True,
        which=lambda name: r"C:\trusted\Microsoft\WindowsApps\winget.exe", popen=Process,
        environ={"LOCALAPPDATA": r"C:\trusted"})
    assert result.returncode == 0 and "installed successfully" in result.output
    assert "supersecret" not in result.output
    assert calls[0][1]["shell"] is False
    assert isinstance(calls[0][0], list)


def test_user_scope_runs_only_in_interactive_context_and_permission_errors_are_clear():
    class Process:
        def __init__(self, _args, **_kwargs):
            pass
        def poll(self):
            return 0
        def wait(self, **_kwargs):
            return 0

    user_offer = offer(installation_scope="USER")
    result = execute_package_job(user_offer, local_system=False, administrator=False,
        service_context=False, which=lambda _name: r"C:\trusted\Microsoft\WindowsApps\winget.exe",
        environ={"LOCALAPPDATA": r"C:\trusted"}, popen=Process)
    assert result.returncode == 0

    with pytest.raises(UnsupportedExecutionContext, match="machine_scope_permission_denied"):
        execute_package_job(offer(), local_system=True, administrator=True, service_context=True,
            which=lambda _name: r"C:\trusted\Microsoft\WindowsApps\winget.exe",
            environ={"LOCALAPPDATA": r"C:\trusted"}, popen=lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError()))


def test_chocolatey_install_and_uninstall_use_only_configured_source_and_exact_id(tmp_path):
    executable = tmp_path / "chocolatey" / "bin" / "choco.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    calls = []

    class Process:
        def __init__(self, args, **kwargs):
            calls.append(args)
        def poll(self):
            return 0
        def wait(self, **_kwargs):
            return 0

    source = "https://packages.example.test/choco/v2/"
    install = offer(package_manager="CHOCO", source="CHOCO_CONFIGURED", source_url=source,
        version="3.2", installation_scope="MACHINE")
    result = execute_package_job(install, local_system=True, administrator=True, service_context=True,
        which=lambda _name: str(executable), environ={"ProgramData": str(tmp_path)}, popen=Process)
    assert result.returncode == 0
    assert calls[-1] == [str(executable), "install", "Vendor.App", "--yes", "--no-progress",
        "--limit-output", "--source", source, "--version", "3.2"]

    uninstall = offer(action="UNINSTALL", package_manager="CHOCO", source="CHOCO_CONFIGURED",
        source_url=source, installation_scope="MACHINE")
    result = execute_package_job(uninstall, local_system=True, administrator=True, service_context=True,
        which=lambda _name: str(executable), environ={"ProgramData": str(tmp_path)}, popen=Process)
    assert result.returncode == 0
    assert calls[-1] == [str(executable), "uninstall", "Vendor.App", "--yes", "--no-progress", "--limit-output"]


def test_package_execution_timeout_and_cancellation_are_reported(monkeypatch):
    class Process:
        terminated = False
        killed = False
        def __init__(self, *_args, **_kwargs):
            pass
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def kill(self):
            self.killed = True
        def wait(self, **_kwargs):
            return -1

    cancelled = threading.Event()
    cancelled.set()
    first = execute_package_job(offer(), local_system=True, administrator=True, service_context=True,
        which=lambda _name: r"C:\trusted\Microsoft\WindowsApps\winget.exe",
        environ={"LOCALAPPDATA": r"C:\trusted"}, popen=Process, cancellation_event=cancelled)
    assert first.cancelled is True

    ticks = iter([0.0, 61.0])
    monkeypatch.setattr("labguard_client.software_management.time.monotonic", lambda: next(ticks))
    timeout = execute_package_job(offer(), local_system=True, administrator=True, service_context=True,
        which=lambda _name: r"C:\trusted\Microsoft\WindowsApps\winget.exe",
        environ={"LOCALAPPDATA": r"C:\trusted"}, popen=Process)
    assert timeout.timed_out is True


def test_windows_administrator_token_check_and_access_denied_fail_closed(monkeypatch):
    monkeypatch.setattr("labguard_client.software_management.os.name", "nt")
    api = types.SimpleNamespace(GetCurrentProcess=lambda: object())
    con = types.SimpleNamespace(TOKEN_QUERY=1)
    security = types.SimpleNamespace(
        OpenProcessToken=lambda *_args: "token",
        GetTokenInformation=lambda *_args: {"TokenIsElevated": 1},
        TokenElevation="TokenElevation",
    )
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setitem(sys.modules, "win32con", con)
    monkeypatch.setitem(sys.modules, "win32security", security)
    assert is_administrator() is True

    def denied(*_args):
        raise OSError("access denied")
    security.OpenProcessToken = denied
    assert is_administrator() is False


def test_reconnected_running_job_is_reported_unknown_without_reexecution(tmp_path, monkeypatch):
    identity = DeviceIdentity.ephemeral()
    identity.state_file = tmp_path / "identity.json"
    client = AgentClient("https://server.example.test", identity)
    job_id = str(uuid4())
    (tmp_path / "software-jobs.json").write_text(json.dumps({
        "version": 1, "jobs": {job_id: {"status": "RUNNING"}},
    }), encoding="utf-8")
    sent = []

    async def send(_ws, event_type, payload, _pending, _lock):
        sent.append((event_type, payload))
        return {"accepted": True}

    monkeypatch.setattr(client, "_send_session_event", send)
    event = offer_payload(job_id=job_id)
    asyncio.run(client._run_software_job(event, object(), {}, asyncio.Lock()))
    saved = json.loads((tmp_path / "software-jobs.json").read_text(encoding="utf-8"))["jobs"][job_id]
    assert saved["result_code"] == "agent_restart_result_unknown"
    assert sent[0][0] == "client.job.failed"


def test_job_reports_lifecycle_and_requires_inventory_verification(tmp_path, monkeypatch):
    identity = DeviceIdentity.ephemeral()
    identity.state_file = tmp_path / "identity.json"
    client = AgentClient("https://server.example.test", identity)
    sent = []

    async def send(_ws, event_type, payload, _pending, _lock):
        sent.append((event_type, payload))
        return {"accepted": True}

    async def inventory(*_args, **_kwargs):
        return True

    class Collected:
        complete = True
        entries = [{"package_id": "Vendor.App", "source": "WINGET"}]

    monkeypatch.setattr(client, "_send_session_event", send)
    monkeypatch.setattr(client, "_collect_and_send_software_inventory", inventory)
    monkeypatch.setattr("labguard_client.agent.collect_software_inventory", lambda: Collected())
    def execute(*_args, **kwargs):
        kwargs["progress"]("Downloading approved package")
        return PackageResult(0, "installed")
    monkeypatch.setattr("labguard_client.agent.execute_package_job", execute)
    asyncio.run(client._run_software_job(offer_payload(), object(), {}, asyncio.Lock()))
    types = [event_type for event_type, _ in sent]
    assert types[:2] == ["client.job.accepted", "client.job.started"]
    assert "client.job.progress" in types
    assert types[-1] == "client.job.completed"
    assert sent[-1][1]["result_code"] == "verified_success"
