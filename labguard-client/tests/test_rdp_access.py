from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import asyncio

import pytest

from labguard_client.agent import AgentClient
from labguard_client import agent as agent_module
from labguard_client.rdp_access import cleanup_expired_rdp_access, prepare_rdp_access


class FakeKey:
    def __init__(self, registry, path):
        self.registry = registry
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeRegistry:
    HKEY_LOCAL_MACHINE = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self, edition="Professional", deny=1, policy=None):
        self.values = {
            (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "EditionID"): (edition, self.REG_SZ),
        }
        if deny is not None:
            self.values[(r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")] = (deny, self.REG_DWORD)
        if policy is not None:
            self.values[(r"SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services", "fDenyTSConnections")] = (policy, self.REG_DWORD)

    def OpenKey(self, _root, path, _reserved, _access):
        return FakeKey(self, path)

    def CreateKeyEx(self, _root, path, _reserved, _access):
        return FakeKey(self, path)

    def QueryValueEx(self, key, name):
        try:
            return self.values[(key.path, name)]
        except KeyError as exc:
            raise FileNotFoundError from exc

    def SetValueEx(self, key, name, _reserved, value_type, value):
        self.values[(key.path, name)] = (value, value_type)

    def DeleteValue(self, key, name):
        try:
            del self.values[(key.path, name)]
        except KeyError as exc:
            raise FileNotFoundError from exc


def test_rdp_request_sets_temporary_local_subnet_rules_and_restores_state():
    registry = FakeRegistry()
    calls = []
    now = datetime(2026, 11, 7, tzinfo=UTC)

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="Ok", stderr="")

    request_id = str(uuid4())
    expiry = now + timedelta(minutes=60)
    result = prepare_rdp_access(request_id, expiry.isoformat(), registry_module=registry,
        run_process=run, windows=True, system_root="C:\\Windows", now=now, elevated=True)

    assert result == {"status": "READY", "error_code": None}
    assert registry.values[(r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")] == (0, registry.REG_DWORD)
    assert len(calls) == 2
    assert all(call[1]["shell"] is False for call in calls)
    assert {next(arg.split("=", 1)[1] for arg in call[0] if arg.startswith("profile=")) for call in calls} == {"domain", "private"}
    assert all("remoteip=localsubnet" in call[0] and "public" not in call[0] for call in calls)

    # A repeated admin request extends the existing lease without duplicating firewall rules.
    next_expiry = now + timedelta(minutes=61)
    second = prepare_rdp_access(str(uuid4()), next_expiry.isoformat(), registry_module=registry,
        run_process=run, windows=True, system_root="C:\\Windows", now=now + timedelta(minutes=1), elevated=True)
    assert second["status"] == "READY"
    assert len(calls) == 2
    assert not cleanup_expired_rdp_access(registry_module=registry, run_process=run,
        windows=True, system_root="C:\\Windows", now=next_expiry - timedelta(seconds=1))
    assert cleanup_expired_rdp_access(registry_module=registry, run_process=run,
        windows=True, system_root="C:\\Windows", now=next_expiry + timedelta(seconds=1))
    assert registry.values[(r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")] == (1, registry.REG_DWORD)
    assert (r"SYSTEM\CurrentControlSet\Control\Terminal Server", "LabGuardTemporaryRdpState") not in registry.values
    assert len(calls) == 4
    assert all("delete" in call[0] for call in calls[2:])


def test_rdp_request_respects_windows_policy_and_unsupported_home_edition():
    now = datetime.now(UTC)
    expires = (now + timedelta(minutes=30)).isoformat()
    policy = FakeRegistry(policy=1)
    result = prepare_rdp_access(str(uuid4()), expires, registry_module=policy,
                                run_process=lambda *_a, **_k: pytest.fail("should not run"),
                                windows=True, now=now, elevated=True)
    assert result["error_code"] == "rdp_disabled_by_policy"
    assert (r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections") in policy.values

    home = FakeRegistry(edition="Core")
    result = prepare_rdp_access(str(uuid4()), expires, registry_module=home,
                                run_process=lambda *_a, **_k: pytest.fail("should not run"),
                                windows=True, now=now, elevated=True)
    assert result["error_code"] == "rdp_host_unsupported_edition"


def test_agent_shutdown_revokes_an_active_rdp_lease_immediately():
    registry = FakeRegistry(deny=1)
    calls = []
    now = datetime.now(UTC)

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="Ok", stderr="")

    result = prepare_rdp_access(str(uuid4()), (now + timedelta(minutes=60)).isoformat(),
        registry_module=registry, run_process=run, windows=True, now=now,
        system_root="C:\\Windows", elevated=True)
    assert result["status"] == "READY"
    assert cleanup_expired_rdp_access(registry_module=registry, run_process=run,
        windows=True, now=now + timedelta(minutes=1), force=True)
    assert registry.values[(r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")] == (1, registry.REG_DWORD)
    assert len(calls) == 4


def test_rdp_request_rejects_expired_or_malformed_data_and_non_windows():
    now = datetime.now(UTC)
    registry = FakeRegistry()
    assert prepare_rdp_access("bad", now.isoformat(), registry_module=registry, windows=True, now=now)["status"] == "FAILED"
    assert prepare_rdp_access(str(uuid4()), now.isoformat(), registry_module=registry, windows=True, now=now)["error_code"] == "invalid_rdp_lease"
    assert prepare_rdp_access(str(uuid4()), (now + timedelta(minutes=30)).isoformat(), windows=False)["error_code"] == "rdp_windows_only"
    assert prepare_rdp_access(str(uuid4()), (now + timedelta(minutes=30)).isoformat(), registry_module=registry,
        windows=True, now=now, elevated=False)["error_code"] == "rdp_requires_elevation"


def test_agent_reports_typed_rdp_result_without_passing_windows_credentials(monkeypatch):
    now = datetime.now(UTC)
    request_id = str(uuid4())
    sent = []
    client = AgentClient.__new__(AgentClient)
    monkeypatch.setattr(agent_module, "prepare_rdp_access",
        lambda *_args, **_kwargs: {"status": "READY", "error_code": None})
    monkeypatch.setattr(agent_module, "active_windows_username", lambda: "LAB-PC-01\\student")

    async def send(_ws, event_type, payload, _pending, _send_lock):
        sent.append((event_type, payload))
        return {"accepted": True}

    client._send_session_event = send
    asyncio.run(client._run_rdp_access_request({
        "request_id": request_id,
        "expires_at": (now + timedelta(minutes=1)).isoformat(),
        "access_expires_at": (now + timedelta(minutes=30)).isoformat(),
    }, object(), {}, asyncio.Lock()))
    assert sent == [("client.rdp.access.result", {
        "request_id": request_id, "status": "READY", "error_code": None,
        "username": "LAB-PC-01\\student",
    })]
    assert all("password" not in key.casefold() for _event, payload in sent for key in payload)
