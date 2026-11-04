import base64
import json
import sys
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


def test_plain_http_requires_explicit_development_opt_in():
    identity = DeviceIdentity.ephemeral()
    with pytest.raises(ValueError, match="explicitly enabled"):
        AgentClient("http://127.0.0.1:8000", identity)
    client = AgentClient("http://127.0.0.1:8000", identity, allow_insecure_dev=True)
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
    with pytest.raises(ValueError, match="HTTPS"):
        AgentConfig("http://labguard.example.test", tmp_path)
    with pytest.raises(ValueError, match="embedded credentials"):
        AgentConfig("https://admin:password@labguard.example.test", tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        AgentConfig("https://labguard.example.test", Path("relative"))
