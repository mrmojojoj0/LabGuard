import base64
import json
import sys
import threading
import types
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity


def test_identity_persists_key_and_sequence_with_dpapi_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("labguard_client.identity.platform.system", lambda: "Windows")
    fake_dpapi = types.SimpleNamespace(
        CryptProtectData=lambda data, *args: b"protected:" + data,
        CryptUnprotectData=lambda data, *args: ("description", data.removeprefix(b"protected:")),
    )
    monkeypatch.setitem(sys.modules, "win32crypt", fake_dpapi)
    identity = DeviceIdentity.load_or_create(tmp_path)
    first_signature = identity.sign(b"before-reload")
    assert identity.next_sequence() == 1
    reloaded = DeviceIdentity.load_or_create(tmp_path)
    assert reloaded.device_id == identity.device_id
    assert reloaded.sequence == 1
    reloaded.private_key.public_key().verify(first_signature, b"before-reload")
    assert (tmp_path / "identity.json").exists()


def test_identity_migrates_to_machine_dpapi_without_changing_key(tmp_path, monkeypatch):
    monkeypatch.setattr("labguard_client.identity.platform.system", lambda: "Windows")
    flags = []
    fake_dpapi = types.SimpleNamespace(
        CryptProtectData=lambda data, *args: (flags.append(args[-1]) or b"protected:" + data),
        CryptUnprotectData=lambda data, *args: ("description", data.removeprefix(b"protected:")),
    )
    monkeypatch.setitem(sys.modules, "win32crypt", fake_dpapi)
    identity = DeviceIdentity.load_or_create(tmp_path)
    original_id = identity.device_id
    identity.protection_scope = "machine"
    identity._save()
    reloaded = DeviceIdentity.load_existing(tmp_path)
    assert reloaded.device_id == original_id
    assert reloaded.protection_scope == "machine"
    assert flags[-1] == 0x4


def test_load_existing_never_generates_identity(tmp_path):
    with pytest.raises(FileNotFoundError, match="Device identity not found"):
        DeviceIdentity.load_existing(tmp_path)
    assert not (tmp_path / "identity.json").exists()


def test_plain_http_is_supported_alongside_https():
    identity = DeviceIdentity.ephemeral()
    client = AgentClient("http://127.0.0.1:8000", identity)
    assert client.server_url == "http://127.0.0.1:8000"
    assert client.ssl_context.check_hostname
    assert client.ssl_context.verify_mode == 2


def test_https_tls_context_keeps_certificate_verification():
    client = AgentClient("https://labguard.example.test", DeviceIdentity.ephemeral())
    assert client.ssl_context.check_hostname is True
    assert client.ssl_context.verify_mode == 2


def test_device_proof_uses_server_nonce_and_ed25519_identity(monkeypatch):
    identity = DeviceIdentity.ephemeral()
    nonce = "server-generated-nonce"
    challenge_id = str(uuid4())
    calls = []
    def post(path, payload):
        calls.append((path, payload))
        if path.endswith("challenge"):
            return {"challenge_id": challenge_id, "nonce": nonce}
        return {"ticket": "one-use-ticket"}
    client = AgentClient("https://labguard.example.test", identity)
    monkeypatch.setattr(client, "_post", post)
    assert client._ticket() == "one-use-ticket"
    assert calls[0][0] == "/api/v1/agent/challenge"
    signature = base64.urlsafe_b64decode(calls[1][1]["signature"] + "==")
    key = serialization.load_pem_public_key(identity.public_key_pem().encode("ascii"))
    assert isinstance(key, Ed25519PublicKey)
    nonce_hash = __import__("hashlib").sha256(nonce.encode("ascii")).hexdigest()
    message = f"labguard.device.auth.v1\n{identity.device_id}\n{challenge_id}\n{nonce_hash}".encode("ascii")
    key.verify(signature, message)
def test_run_forever_retries_after_connection_failure(monkeypatch):
    import asyncio
    from labguard_client.agent import AgentClient

    async def exercise():
        client = AgentClient("https://labguard.example.test", DeviceIdentity.ephemeral())
        stop = asyncio.Event()
        calls = 0
        waits = []

        class FakeSocket:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None

        async def connect_once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("temporary outage")
            stop.set()
            return FakeSocket()

        async def wait_or_stop(_stop, delay):
            waits.append(delay)
            return False

        monkeypatch.setattr(client, "connect_once", connect_once)
        monkeypatch.setattr(client, "_wait_or_stop", wait_or_stop)
        await asyncio.wait_for(client.run_forever(stop), timeout=1)
        assert calls == 2
        assert waits[0] <= 1.0

    asyncio.run(exercise())


def test_run_forever_cancels_connection_attempt_promptly():
    import asyncio

    async def exercise():
        client = AgentClient("https://labguard.example.test", DeviceIdentity.ephemeral())
        stop = asyncio.Event()
        canceled = asyncio.Event()

        async def blocked_connect():
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

        client.connect_once = blocked_connect
        task = asyncio.create_task(client.run_forever(stop))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=0.5)
        assert canceled.is_set()

    asyncio.run(exercise())


def test_instance_lock_rejects_duplicate_process(tmp_path):
    from labguard_client.instance import IdentityProcessLock, InstanceAlreadyRunning

    first = IdentityProcessLock(tmp_path / "agent.lock")
    second = IdentityProcessLock(tmp_path / "agent.lock")
    first.acquire()
    try:
        with pytest.raises(InstanceAlreadyRunning):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_service_configuration_validation_and_persistence(tmp_path):
    from labguard_client.service_config import AgentConfig

    config = AgentConfig("https://labguard.example.test", tmp_path)
    path = tmp_path / "service.json"
    config.write(path)
    assert AgentConfig.load(path) == config
    legacy_path = tmp_path / "legacy-service.json"
    legacy_path.write_text('{"server_url":"https://labguard.example.test","state_dir":"' +
        str(tmp_path).replace("\\", "\\\\") + '"}', encoding="utf-8")
    assert AgentConfig.load(legacy_path).allow_insecure_dev is False
    http_config = AgentConfig("http://labguard.example.test", tmp_path)
    http_path = tmp_path / "service-http.json"
    http_config.write(http_path)
    assert AgentConfig.load(http_path) == http_config
    assert AgentConfig("https://labguard.example.test", tmp_path).server_url.startswith("https://")
    with pytest.raises(ValueError, match="embedded credentials"):
        AgentConfig("https://admin:password@labguard.example.test", tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        AgentConfig("https://labguard.example.test", Path("relative"))
    with pytest.raises(ValueError, match="telemetry_interval"):
        AgentConfig("https://labguard.example.test", tmp_path, telemetry_interval_seconds=5)


def test_service_prepare_preserves_existing_identity_and_migrates_protection(tmp_path, monkeypatch):
    from labguard_client import windows_service
    from labguard_client.identity import DeviceIdentity

    monkeypatch.setattr("labguard_client.identity.platform.system", lambda: "Windows")
    fake_dpapi = types.SimpleNamespace(
        CryptProtectData=lambda data, *args: b"protected:" + data,
        CryptUnprotectData=lambda data, *args: ("description", data.removeprefix(b"protected:")),
    )
    monkeypatch.setitem(sys.modules, "win32crypt", fake_dpapi)

    state_dir = tmp_path / "state"
    original = DeviceIdentity.load_or_create(state_dir)
    original_id = original.device_id
    original_signature = original.sign(b"preserve-enrolled-key")
    config_path = tmp_path / "service.json"
    monkeypatch.setattr(windows_service, "CONFIG_PATH", config_path)
    monkeypatch.setattr("labguard_client.windows_security.secure_state_directory", lambda _path: None)

    assert windows_service.prepare_service("https://labguard.example.test", state_dir) == config_path

    reloaded = DeviceIdentity.load_existing(state_dir)
    assert reloaded.device_id == original_id
    assert reloaded.protection_scope == "machine"
    reloaded.private_key.public_key().verify(original_signature, b"preserve-enrolled-key")
    assert config_path.is_file()


def test_service_startup_uses_persisted_development_transport_setting(tmp_path):
    from labguard_client.service_config import AgentConfig
    from labguard_client.windows_service import create_service_client

    config_path = tmp_path / "service.json"
    AgentConfig("http://127.0.0.1:8000", tmp_path, allow_insecure_dev=True).write(config_path)
    config = AgentConfig.load(config_path)
    client = create_service_client(config, DeviceIdentity.ephemeral())
    assert client.server_url == "http://127.0.0.1:8000"
    assert client.ssl_context.check_hostname is True
    assert client.ssl_context.verify_mode == 2


def test_service_cli_requires_and_forwards_explicit_development_flag(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    import labguard_client.cli as cli

    calls = []
    fake_service = SimpleNamespace(
        prepare_service=lambda *args, **kwargs: calls.append(("prepare", args, kwargs)) or tmp_path / "service.json",
        service_command=lambda *args, **kwargs: calls.append(("install", args, kwargs)) or "installed",
    )
    monkeypatch.setitem(sys.modules, "labguard_client.windows_service", fake_service)
    monkeypatch.setattr(cli, "_configure_logging", lambda _path: None)
    monkeypatch.setattr(sys, "argv", ["labguard-agent", "service", "prepare", "--server",
        "http://127.0.0.1:8000", "--state-dir", str(tmp_path), "--insecure-dev"])
    cli.main()
    assert calls[-1][0] == "prepare"
    assert calls[-1][2]["allow_insecure_dev"] is True

    monkeypatch.setattr(sys, "argv", ["labguard-agent", "service", "install", "--state-dir",
        str(tmp_path), "--insecure-dev"])
    cli.main()
    assert calls[-1] == ("install", ("install",), {"insecure_dev": True})


def test_service_install_accepts_http_config_without_special_flag(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from labguard_client import windows_service
    from labguard_client.service_config import AgentConfig

    config = AgentConfig("http://127.0.0.1:8000", tmp_path)
    monkeypatch.setattr(windows_service, "CONFIG_PATH", tmp_path / "service.json")
    config.write(windows_service.CONFIG_PATH)
    (tmp_path / "identity.json").write_text("{}", encoding="utf-8")
    util = SimpleNamespace(QueryServiceStatus=lambda _name: (_ for _ in ()).throw(OSError()),
        InstallService=lambda *_args, **_kwargs: install_calls.append((_args, _kwargs)))
    install_calls = []
    monkeypatch.setattr(windows_service, "_require_windows",
        lambda: (SimpleNamespace(SERVICE_AUTO_START=2), util))
    staged_host = tmp_path / "venv" / "Scripts" / "pythonservice.exe"
    monkeypatch.setattr(windows_service, "_service_host_executable", lambda _service: staged_host)
    assert windows_service.service_command("install").startswith("Installed")
    assert install_calls[0][1]["exeName"] == str(staged_host)


def test_venv_service_host_is_staged_in_scripts_with_required_runtime_dlls(tmp_path):
    from labguard_client.windows_service import _stage_venv_service_host

    venv_root = tmp_path / ".venv"
    source_dir = tmp_path / "runtime"
    dll_dir = tmp_path / "pywin32_system32"
    source_dir.mkdir()
    dll_dir.mkdir()
    host = source_dir / "pythonservice.exe"
    python_dll = source_dir / "python312.dll"
    pywintypes_dll = dll_dir / "pywintypes312.dll"
    pythoncom_dll = dll_dir / "pythoncom312.dll"
    for file in (host, python_dll, pywintypes_dll, pythoncom_dll):
        file.write_bytes(file.name.encode("ascii"))

    staged = _stage_venv_service_host(venv_root, host, python_dll, dll_dir, "312")
    assert staged == venv_root / "Scripts" / "pythonservice.exe"
    for file in (host, python_dll, pywintypes_dll, pythoncom_dll):
        assert (staged.parent / file.name).read_bytes() == file.name.encode("ascii")


def test_service_registers_and_retains_base_python_dll_directory(tmp_path, monkeypatch):
    from labguard_client import windows_service

    (tmp_path / "python3.dll").write_bytes(b"runtime marker")
    handle = object()
    registered = []
    monkeypatch.setattr(windows_service.sys, "base_prefix", str(tmp_path))
    monkeypatch.setattr(windows_service.os, "add_dll_directory",
                        lambda directory: registered.append(directory) or handle, raising=False)
    monkeypatch.setattr(windows_service, "_NATIVE_DLL_DIRECTORY_HANDLES", [])

    windows_service._prepare_native_dll_search()

    assert registered == [str(tmp_path)]
    assert windows_service._NATIVE_DLL_DIRECTORY_HANDLES == [handle]


def test_service_selector_loop_starts_and_stops_in_worker_thread():
    import asyncio
    from labguard_client import windows_service

    ready = threading.Event()
    finished = threading.Event()
    result = {}

    def service_thread():
        loop = windows_service._create_service_event_loop()
        result["loop_type"] = type(loop)
        result["installed_in_thread"] = asyncio.get_event_loop() is loop
        stop_event = asyncio.Event()
        result["loop"] = loop
        result["stop_event"] = stop_event

        async def wait_for_stop():
            ready.set()
            await stop_event.wait()
            return "stopped"

        try:
            result["run_result"] = loop.run_until_complete(wait_for_stop())
        except BaseException as exc:
            result["error"] = exc
        finally:
            loop.close()
            asyncio.set_event_loop(None)
            finished.set()

    worker = threading.Thread(target=service_thread)
    worker.start()
    assert ready.wait(timeout=2)
    windows_service._signal_async_stop(result["loop"], result["stop_event"])
    worker.join(timeout=2)

    assert finished.is_set()
    assert not worker.is_alive()
    assert result["loop_type"] is asyncio.SelectorEventLoop
    assert result["installed_in_thread"] is True
    assert result["run_result"] == "stopped"
    assert "error" not in result


def test_service_install_updates_stopped_service_host_without_changing_identity(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from labguard_client import windows_service
    from labguard_client.service_config import AgentConfig

    config = AgentConfig("https://labguard.example.test", tmp_path)
    monkeypatch.setattr(windows_service, "CONFIG_PATH", tmp_path / "service.json")
    config.write(windows_service.CONFIG_PATH)
    (tmp_path / "identity.json").write_text("protected identity", encoding="utf-8")
    staged_host = tmp_path / "venv" / "Scripts" / "pythonservice.exe"
    monkeypatch.setattr(windows_service, "_service_host_executable", lambda _service: staged_host)
    updates = []
    util = SimpleNamespace(
        QueryServiceStatus=lambda _name: (0, 1),
        ChangeServiceConfig=lambda *args, **kwargs: updates.append((args, kwargs)),
        InstallService=lambda *_args, **_kwargs: pytest.fail("existing service should be updated"),
    )
    service_api = SimpleNamespace(SERVICE_AUTO_START=2, SERVICE_STOPPED=1)
    monkeypatch.setattr(windows_service, "_require_windows", lambda: (service_api, util))

    result = windows_service.service_command("install")
    assert "Updated" in result
    assert updates[0][1]["exeName"] == str(staged_host)
    assert "userName" not in updates[0][1]
    assert "password" not in updates[0][1]


def test_secure_state_directory_assigns_full_file_rights_only_to_allowed_sids(tmp_path, monkeypatch):
    from labguard_client import windows_security

    monkeypatch.setattr(windows_security.os, "name", "nt")
    child_file = tmp_path / "identity.json"
    child_file.write_text("protected", encoding="utf-8")
    child_dir = tmp_path / "nested"
    child_dir.mkdir()

    grants = []
    applied = []
    class FakeAcl:
        def AddAccessAllowedAceEx(self, revision, flags, mask, sid):
            grants.append((revision, flags, mask, sid))
    current_user = "S-1-5-21-enrolling-user"
    sid_system = "S-1-5-18"
    sid_admins = "S-1-5-32-544"
    win32api = types.SimpleNamespace(GetCurrentProcess=lambda: "process")
    win32con = types.SimpleNamespace(TOKEN_QUERY=0x8, GENERIC_ALL=0x10000000)
    win32security = types.SimpleNamespace(
        OpenProcessToken=lambda process, access: (process, access),
        GetTokenInformation=lambda _token, _info: (current_user, 0),
        TokenUser=1,
        CreateWellKnownSid=lambda kind, _domain: {5: sid_system, 26: sid_admins}[kind],
        WinLocalSystemSid=5,
        WinBuiltinAdministratorsSid=26,
        ACL=FakeAcl,
        OBJECT_INHERIT_ACE=0x1,
        CONTAINER_INHERIT_ACE=0x2,
        ACL_REVISION_DS=4,
        SetNamedSecurityInfo=lambda *args: applied.append(args),
        SE_FILE_OBJECT=1,
        DACL_SECURITY_INFORMATION=0x4,
        PROTECTED_DACL_SECURITY_INFORMATION=0x80000000,
    )
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(sys.modules, "win32con", win32con)
    monkeypatch.setitem(sys.modules, "win32security", win32security)

    windows_security.secure_state_directory(tmp_path)

    assert grants == [
        (4, 0x3, 0x10000000, sid_system),
        (4, 0x3, 0x10000000, sid_admins),
        (4, 0x3, 0x10000000, current_user),
    ]
    assert len(applied) == 2
    assert {row[0] for row in applied} == {str(tmp_path), str(child_file)}
    for target, object_type, flags, owner, group, acl, _sacl in applied:
        assert object_type == 1
        assert flags == 0x4 | 0x80000000
        assert owner is None and group is None
        assert isinstance(acl, FakeAcl)


def test_pywin_service_reports_running_before_config_and_logs_startup_exception(tmp_path, monkeypatch):
    import os
    from labguard_client import windows_service

    if os.name != "nt" or not hasattr(windows_service, "LabGuardWindowsService"):
        pytest.skip("pywin32 ServiceFramework lifecycle is Windows-only")

    config_path = tmp_path / "ProgramData" / "LabGuard" / "service.json"
    monkeypatch.setattr(windows_service, "CONFIG_PATH", config_path)
    events = []
    def fail_load(_path):
        events.append("config_load")
        raise RuntimeError("synthetic startup configuration failure")
    monkeypatch.setattr(windows_service.AgentConfig, "load", fail_load)
    event_log = []
    monkeypatch.setattr(windows_service.servicemanager, "LogErrorMsg", event_log.append)

    service = object.__new__(windows_service.LabGuardWindowsService)
    service._loop = None
    service._async_stop = None
    service._stop_requested = threading.Event()
    def report(status, **_kwargs):
        events.append(("status", status))
    service.ReportServiceStatus = report

    with pytest.raises(RuntimeError, match="synthetic startup"):
        service.SvcRun()

    running_status = windows_service.win32service.SERVICE_RUNNING
    assert events.index(("status", running_status)) < events.index("config_load")
    assert event_log == ["LabGuard Agent failed: RuntimeError"]
    log_text = (config_path.parent / "labguard-agent.log").read_text(encoding="utf-8")
    assert "Windows service startup/runtime failed" in log_text
    assert "synthetic startup configuration failure" in log_text


def test_pywin_service_stop_and_shutdown_signal_async_loop(tmp_path):
    import os
    from labguard_client import windows_service

    if os.name != "nt" or not hasattr(windows_service, "LabGuardWindowsService"):
        pytest.skip("pywin32 ServiceFramework lifecycle is Windows-only")

    class StopSignal:
        stopped = False
        def set(self):
            self.stopped = True

    class EventLoop:
        closed = False
        def is_closed(self):
            return self.closed
        def call_soon_threadsafe(self, callback):
            callback()

    statuses = []
    service = object.__new__(windows_service.LabGuardWindowsService)
    service._loop = EventLoop()
    service._async_stop = StopSignal()
    service._stop_requested = threading.Event()
    service.ReportServiceStatus = lambda status, **_kwargs: statuses.append(status)

    service.SvcStop()
    assert service._stop_requested.is_set()
    assert service._async_stop.stopped is True
    assert statuses[-1] == windows_service.win32service.SERVICE_STOP_PENDING

    service._async_stop.stopped = False
    service._stop_requested.clear()
    service.SvcShutdown()
    assert service._stop_requested.is_set()
    assert service._async_stop.stopped is True
    assert statuses[-1] == windows_service.win32service.SERVICE_STOP_PENDING


def test_telemetry_collection_fields_and_missing_information(monkeypatch):
    from types import SimpleNamespace
    import labguard_client.telemetry as telemetry

    monkeypatch.setattr(telemetry.psutil, "cpu_percent", lambda interval=None: 22.5)
    monkeypatch.setattr(telemetry.psutil, "virtual_memory", lambda: SimpleNamespace(total=1000, used=400, available=600, percent=40.0))
    monkeypatch.setattr(telemetry.psutil, "boot_time", lambda: 1000.0)
    monkeypatch.setattr(telemetry.psutil, "cpu_count", lambda logical=True: 4 if logical else 2)
    monkeypatch.setattr(telemetry.psutil, "disk_partitions", lambda all=False: [])
    monkeypatch.setattr(telemetry.psutil, "net_if_addrs", lambda: {})
    monkeypatch.setattr(telemetry.psutil, "net_if_stats", lambda: {})
    monkeypatch.setattr(telemetry, "_processor_name", lambda: None)
    monkeypatch.setattr(telemetry, "_windows_edition", lambda: None)
    monkeypatch.setattr(telemetry, "active_windows_username", lambda: "LAB-PC-01\\student")
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(telemetry.platform, "win32_ver", lambda: ("", "", "", ""))
    monkeypatch.setattr("labguard_client.telemetry.time.time", lambda: 2000.0)
    result = telemetry.collect_system_telemetry()
    assert result["cpu"] == {"processor_name": None, "logical_processors": 4, "physical_cores": 2, "utilization_percent": 22.5}
    assert result["storage_partitions"] == []
    assert result["network_interfaces"] == []
    assert result["operating_system"]["edition"] is None
    assert result["operating_system"]["username"] == "LAB-PC-01\\student"
    assert result["uptime_seconds"] == 1000
    assert result["collected_at"] and result["boot_time"]


def test_telemetry_collects_disk_and_interface_details(monkeypatch):
    from types import SimpleNamespace
    import socket
    import labguard_client.telemetry as telemetry

    partition = SimpleNamespace(device="C:\\", mountpoint="C:\\", fstype="NTFS")
    addresses = [SimpleNamespace(family=socket.AF_INET, address="192.0.2.8"),
                 SimpleNamespace(family=socket.AF_INET6, address="2001:db8::8%12"),
                 SimpleNamespace(family=getattr(telemetry.psutil, "AF_LINK", -1), address="AA:BB:CC:DD:EE:FF")]
    monkeypatch.setattr(telemetry.psutil, "cpu_percent", lambda interval=None: 5.0)
    monkeypatch.setattr(telemetry.psutil, "virtual_memory", lambda: SimpleNamespace(total=1000, used=250, available=750, percent=25.0))
    monkeypatch.setattr(telemetry.psutil, "boot_time", lambda: 1000.0)
    monkeypatch.setattr(telemetry.psutil, "cpu_count", lambda logical=True: 4 if logical else 2)
    monkeypatch.setattr(telemetry.psutil, "disk_partitions", lambda all=False: [partition])
    monkeypatch.setattr(telemetry.psutil, "disk_usage", lambda _path: SimpleNamespace(total=1000, used=400, free=600, percent=40.0))
    monkeypatch.setattr(telemetry.psutil, "net_if_addrs", lambda: {"Ethernet": addresses})
    monkeypatch.setattr(telemetry.psutil, "net_if_stats", lambda: {"Ethernet": SimpleNamespace(isup=True, speed=1000)})
    monkeypatch.setattr(telemetry, "_processor_name", lambda: "Test Processor")
    monkeypatch.setattr(telemetry, "_windows_edition", lambda: "Windows Education")
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(telemetry.platform, "win32_ver", lambda: ("Windows", "10.0", "", ""))

    result = telemetry.collect_system_telemetry()
    assert result["storage_partitions"][0]["utilization_percent"] == 40
    interface = result["network_interfaces"][0]
    assert interface["status"] == "UP" and interface["speed_mbps"] == 1000
    assert interface["ipv4_addresses"] == ["192.0.2.8"]
    assert interface["ipv6_addresses"] == ["2001:db8::8"]
    assert interface["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert result["operating_system"]["edition"] == "Windows Education"
