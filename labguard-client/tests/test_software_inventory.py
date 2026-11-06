from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace

from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity
from labguard_client.service_config import AgentConfig
from labguard_client.software_inventory import batch_entries, collect_software_inventory, inventory_digest


class _Key:
    def __init__(self, registry, root, path, view):
        self.registry, self.root, self.path, self.view = registry, root, path, view

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Registry:
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    HKEY_USERS = "HKU"
    KEY_READ = 1
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200

    def __init__(self):
        self.bases = {}
        self.values = {}
        self.users = ["S-1-5-21-1-2-3-1001", ".DEFAULT", "S-1-5-18"]

    def add(self, root, path, view, subkey, values):
        self.bases.setdefault((root, path, view), []).append(subkey)
        self.values[(root, path, view, subkey)] = values

    def OpenKey(self, root, path, _reserved=0, access=0):
        if isinstance(root, _Key):
            root_name = root.root
            full_path = root.path + ("\\" + path if path else "")
            view = access & (self.KEY_WOW64_64KEY | self.KEY_WOW64_32KEY) or root.view
        else:
            root_name, full_path = root, path
            view = access & (self.KEY_WOW64_64KEY | self.KEY_WOW64_32KEY)
        if root_name == self.HKEY_USERS and full_path == "":
            return _Key(self, root_name, full_path, view)
        if (root_name, full_path, view) in self.bases:
            return _Key(self, root_name, full_path, view)
        if full_path.endswith("\\Denied"):
            exc = PermissionError("access denied")
            exc.winerror = 5
            raise exc
        if (root_name, full_path.rsplit("\\", 1)[0], view) in self.bases:
            return _Key(self, root_name, full_path, view)
        raise FileNotFoundError(full_path)

    def EnumKey(self, key, index):
        if key.root == self.HKEY_USERS and key.path == "":
            values = self.users
        else:
            values = self.bases[(key.root, key.path, key.view)]
        if index >= len(values):
            raise OSError("no more subkeys")
        return values[index]

    def QueryValueEx(self, key, name):
        try:
            value = self.values[(key.root, key.path.rsplit("\\", 1)[0], key.view, key.path.rsplit("\\", 1)[1])][name]
        except KeyError as exc:
            raise FileNotFoundError(name) from exc
        return value, 1


def test_registry_collector_reads_both_views_loaded_profiles_and_deduplicates():
    registry = _Registry()
    from labguard_client.software_inventory import REGISTRY_PATH
    registry.add("HKLM", REGISTRY_PATH, 0x100, "app-one", {
        "DisplayName": "Example App", "DisplayVersion": "2.0", "Publisher": "Example Co",
        "InstallDate": "20250130", "InstallLocation": "C:\\Program Files\\Example"})
    registry.add("HKLM", REGISTRY_PATH, 0x100, "duplicate", {
        "DisplayName": "Example App", "DisplayVersion": "2.0", "Publisher": "Example Co",
        "InstallDate": "20250130", "InstallLocation": "C:\\Program Files\\Example"})
    registry.add("HKLM", REGISTRY_PATH, 0x200, "legacy", {"DisplayName": "Legacy", "Publisher": "Old Co"})
    registry.add("HKLM", REGISTRY_PATH, 0x100, "vc-x86", {
        "DisplayName": "Visual C++ Runtime", "Publisher": "Microsoft", "Architecture": "x86",
        "InstallLocation": "C:\\Runtime\\x86"})
    registry.add("HKLM", REGISTRY_PATH, 0x200, "vc-x64", {
        "DisplayName": "Visual C++ Runtime", "Publisher": "Microsoft", "Architecture": "x64",
        "InstallLocation": "C:\\Runtime\\x64"})
    registry.add("HKCU", REGISTRY_PATH, 0x100, "missing-version", {"DisplayName": "User App"})
    sid = registry.users[0]
    registry.add("HKU", sid + "\\" + REGISTRY_PATH, 0x100, "user-app", {"DisplayName": "Profile App"})
    # An unreadable entry contributes a diagnostic but does not discard accessible apps.
    registry.bases[("HKLM", REGISTRY_PATH, 0x100)].append("Denied")

    inventory = collect_software_inventory(winreg_module=registry, which=lambda _name: None,
                                           run=lambda _command: "", windows=True)
    names = {(entry["name"], entry["architecture"], entry["installation_scope"]): entry for entry in inventory.entries}
    assert ("Example App", "UNKNOWN", "MACHINE") in names
    assert ("Legacy", "UNKNOWN", "MACHINE") in names
    assert ("Profile App", "UNKNOWN", "USER") in names
    assert names[("User App", "UNKNOWN", "USER")]["version"] is None
    assert ("Visual C++ Runtime", "x86", "MACHINE") in names
    assert ("Visual C++ Runtime", "x64", "MACHINE") in names
    assert sum(entry["name"] == "Example App" for entry in inventory.entries) == 1
    assert "registry_entry_access_denied" in inventory.errors


def test_optional_package_managers_can_be_absent_or_fail_without_losing_registry_data(monkeypatch):
    registry = _Registry()
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    absent = collect_software_inventory(winreg_module=registry, which=lambda _name: None,
                                        run=lambda _command: "", windows=True)
    assert absent.detected_package_managers == []
    assert absent.errors == ["winget_executable_not_found"]

    def fail(_command):
        raise subprocess.TimeoutExpired(_command, 20)

    partial = collect_software_inventory(winreg_module=registry, which=lambda name: name,
                                          run=fail, windows=True)
    assert partial.detected_package_managers == ["WINGET", "CHOCO"]
    assert set(partial.errors) == {"winget_timeout", "chocolatey_timeout"}


def test_registry_inventory_succeeds_when_winget_query_fails():
    registry = _Registry()
    from labguard_client.software_inventory import REGISTRY_PATH
    registry.add("HKLM", REGISTRY_PATH, 0x100, "editor", {
        "DisplayName": "Registry Editor", "DisplayVersion": "3.0", "Publisher": "Example"})

    def fail(_command):
        raise RuntimeError("package_registration:14")

    result = collect_software_inventory(winreg_module=registry,
        which=lambda name: "winget.exe" if name == "winget" else None, run=fail, windows=True)
    assert any(item["name"] == "Registry Editor" for item in result.entries)
    assert "winget_package_registration_unavailable" in result.errors
    assert result.complete is False


def test_winget_failures_have_distinct_diagnostics(caplog):
    from labguard_client.software_inventory import _winget_entries

    failures = [
        (subprocess.TimeoutExpired(["winget"], 20), "winget_timeout"),
        (PermissionError("access denied"), "winget_access_denied"),
        (FileNotFoundError("missing"), "winget_executable_not_found"),
        (RuntimeError("package_registration:14"), "winget_package_registration_unavailable"),
        (RuntimeError("command_failed:1"), "winget_command_failed"),
        (subprocess.SubprocessError("process failed"), "winget_process_error"),
        (ValueError("winget_table_unavailable"), "winget_query_unavailable"),
    ]
    for failure, expected in failures:
        errors = []
        entries, detected = _winget_entries(lambda _name: "winget.exe",
            lambda _command, failure=failure: (_ for _ in ()).throw(failure), errors)
        assert entries == [] and detected is True
        assert errors == [expected]
    assert "WinGet inventory query failed" in caplog.text
    assert "account=" in caplog.text and "session=" in caplog.text


def test_winget_process_failure_classifies_registration_and_access_denial(monkeypatch):
    from labguard_client.software_inventory import _run_fixed_command

    seen = {}
    def fake_run(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=1, stdout="", stderr="App Installer registration failed 0x80073D02")
    monkeypatch.setattr("labguard_client.software_inventory.subprocess.run", fake_run)
    try:
        _run_fixed_command(["winget.exe", "list"])
        raise AssertionError("nonzero process must fail")
    except RuntimeError as exc:
        assert str(exc).startswith("package_registration:1")
    assert seen["kwargs"]["shell"] is False and seen["kwargs"]["timeout"] == 20.0

    monkeypatch.setattr("labguard_client.software_inventory.subprocess.run", lambda *_a, **_k:
        SimpleNamespace(returncode=5, stdout="", stderr="Access is denied (0x80070005)"))
    try:
        _run_fixed_command(["winget.exe", "list"])
        raise AssertionError("access denial must fail")
    except RuntimeError as exc:
        assert str(exc).startswith("access_denied:5")


def test_winget_alias_discovery_uses_current_execution_context(monkeypatch):
    from labguard_client.software_inventory import _winget_entries

    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\service\\AppData\\Local")
    monkeypatch.setattr("labguard_client.software_inventory.os.path.isfile", lambda path: path.lower().endswith("winget.exe"))
    commands = []
    output = f"{'Name':<20} {'Id':<24} {'Version':<12}\n{'Example Editor':<20} {'Example.Editor':<24} {'1.0':<12}\n"
    errors = []
    entries, detected = _winget_entries(lambda _name: None,
        lambda command: commands.append(command) or output, errors)
    assert detected and not errors
    assert commands[0][0].lower().endswith("windowsapps/winget.exe") or commands[0][0].lower().endswith("windowsapps\\winget.exe")
    assert entries[0]["package_id"] == "Example.Editor"


def test_inventory_batching_is_bounded_and_digest_is_stable():
    entries = [{"entry_key": f"{index:064x}", "name": f"Application {index}",
                "install_location": "C:\\Program Files\\" + "x" * 600} for index in range(1200)]
    batches = batch_entries(entries, {"collection_id": "00000000-0000-4000-8000-000000000000", "errors": []})
    assert len(batches) > 1
    assert max(map(len, batches)) <= 100
    assert sum(map(len, batches)) == len(entries)
    assert inventory_digest(entries) == inventory_digest(list(reversed(entries)))


def test_non_windows_and_inventory_interval_validation():
    inventory = collect_software_inventory(windows=False)
    assert inventory.entries == []
    assert inventory.errors == ["windows_software_inventory_unavailable"]
    AgentConfig("https://labguard.example", __import__("pathlib").Path("C:/ProgramData/LabGuard"),
                software_inventory_interval_seconds=21600)


def test_agent_sends_full_initial_inventory_skips_unchanged_and_forces_admin_refresh(tmp_path, monkeypatch):
    identity = DeviceIdentity.load_or_create(tmp_path)
    client = AgentClient("https://labguard.example", identity)
    entry = {"entry_key": "a" * 64, "name": "Editor", "version": "1.0", "publisher": "Acme",
        "architecture": "x64", "install_date": None, "install_location": None, "package_id": "acme.editor",
        "source": "WINDOWS_REGISTRY", "installation_scope": "MACHINE"}
    monkeypatch.setattr("labguard_client.agent.collect_software_inventory",
        lambda: SimpleNamespace(entries=[entry], errors=[], complete=True))

    class Socket:
        def __init__(self):
            self.received = asyncio.Queue()
            self.sent = []
        async def send(self, raw):
            event = json.loads(raw)
            self.sent.append(event)
            await self.received.put(json.dumps({"type": "server.ack", "payload": {
                "event_id": event["event_id"], "accepted": True}}))
        async def recv(self):
            return await self.received.get()

    async def exercise():
        ws = Socket()
        pending = {}
        reader = asyncio.create_task(client._read_session_acks(ws, pending, asyncio.Queue()))
        lock = asyncio.Lock()
        try:
            await client._collect_and_send_software_inventory(ws, pending, lock, request_id=None, force=False)
            await client._collect_and_send_software_inventory(ws, pending, lock, request_id=None, force=False)
            await client._collect_and_send_software_inventory(ws, pending, lock,
                request_id="refresh-1", force=True)
            assert len(ws.sent) == 3
            assert ws.sent[0]["payload"]["entries"] == [entry]
            assert ws.sent[1]["payload"]["unchanged"] is True
            assert ws.sent[1]["payload"]["entries"] == []
            assert ws.sent[2]["payload"]["request_id"] == "refresh-1"
            assert ws.sent[2]["payload"]["entries"] == [entry]
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
    asyncio.run(exercise())
