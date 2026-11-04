import asyncio
import json
import socket
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import uvicorn
import pytest
from sqlalchemy import select

from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity
from labguard_server.config import Settings
from labguard_server.main import create_app
from labguard_server.models import Device, DeviceStatus, DeviceStatusEvent, DeviceTelemetryLatest, TelemetrySample
from tests.conftest import login


def enroll_and_approve(admin_client, assigned_name):
    identity = DeviceIdentity.ephemeral()
    csrf = login(admin_client)
    headers = {"X-CSRF-Token": csrf}
    code = admin_client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    result = admin_client.post("/api/v1/enrollment/request", json={"enrollment_code": code,
        "device_id": identity.device_id, "public_key": identity.public_key_pem(), "hostname": assigned_name})
    assert result.status_code == 201, result.text
    approved = admin_client.post(f"/api/v1/enrollment/requests/{identity.device_id}/approve",
        json={"assigned_name": assigned_name}, headers=headers)
    assert approved.status_code == 200, approved.text
    return identity


def telemetry_payload(hostname):
    return {"collected_at": datetime.now(UTC).isoformat(),
        "cpu": {"processor_name": "Integration CPU", "logical_processors": 8, "physical_cores": 4, "utilization_percent": 33.0},
        "memory": {"total_bytes": 16000000000, "used_bytes": 8000000000, "available_bytes": 8000000000, "utilization_percent": 50.0},
        "storage_partitions": [{"device": "C:", "mountpoint": "C:\\", "filesystem": "NTFS", "total_bytes": 1000,
            "used_bytes": 400, "free_bytes": 600, "utilization_percent": 40.0}],
        "operating_system": {"edition": "Windows Test", "version": "10.0", "build_number": "22631", "architecture": "AMD64", "hostname": hostname},
        "boot_time": (datetime.now(UTC) - timedelta(hours=2)).isoformat(), "uptime_seconds": 7200,
        "network_interfaces": [{"name": "Ethernet", "status": "UP", "mac_address": "00:11:22:33:44:55",
            "ipv4_addresses": ["192.0.2.20"], "ipv6_addresses": ["2001:db8::20"], "speed_mbps": 1000}]}


def test_two_real_client_instances_heartbeat_disconnect_and_reconnect(client, monkeypatch):
    identity_one = enroll_and_approve(client, "WS-PC-01")
    identity_two = enroll_and_approve(client, "WS-PC-02")
    identity_three = enroll_and_approve(client, "WS-PC-03")
    database_url = str(client.app.state.engine.url)
    settings = Settings(database_url, "test-session-secret-that-is-at-least-32-chars", cookie_secure=False,
        app_env="test", heartbeat_interval_seconds=0.1, delayed_after_seconds=0.25,
        offline_after_seconds=0.5, device_challenge_ttl_seconds=10, device_ticket_ttl_seconds=10)
    server_app = create_app(settings)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(server_app, host="127.0.0.1", port=port, log_level="critical", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "ASGI test server failed to start"

    agent_one = AgentClient(base_url, identity_one, heartbeat_interval=0.1, allow_insecure_dev=True)
    agent_two = AgentClient(base_url, identity_two, heartbeat_interval=0.1, allow_insecure_dev=True)
    impostor_identity = DeviceIdentity.ephemeral(identity_one.device_id)
    impostor = AgentClient(base_url, impostor_identity, allow_insecure_dev=True)

    async def exercise():
        with pytest.raises(RuntimeError, match=r"Server rejected request \(401\)"):
            await asyncio.to_thread(impostor._ticket)
        ws_one = await agent_one.connect_once()
        ws_two = await agent_two.connect_once()
        async def submit_telemetry(agent, ws, hostname, payload=None):
            envelope = agent._envelope("client.telemetry", payload if payload is not None else telemetry_payload(hostname))
            await ws.send(json.dumps(envelope, separators=(",", ":")))
            return json.loads(await asyncio.wait_for(ws.recv(), 2))
        reports = await asyncio.gather(submit_telemetry(agent_one, ws_one, "WS-PC-01"),
                                       submit_telemetry(agent_two, ws_two, "WS-PC-02"))
        assert all(report["type"] == "server.ack" and report["payload"]["accepted"] for report in reports)
        await agent_one.heartbeat(ws_one)
        await agent_two.heartbeat(ws_two)
        await ws_two.close()

        # Keep the first device healthy while the second remains disconnected past OFFLINE threshold.
        for _ in range(7):
            await asyncio.sleep(0.1)
            await agent_one.heartbeat(ws_one)
        with server_app.state.session_factory() as db:
            first_state = db.get(DeviceStatus, UUID(identity_one.device_id)).agent_state
            second_state = db.get(DeviceStatus, UUID(identity_two.device_id)).agent_state
            assert db.get(Device, UUID(identity_one.device_id)).last_seen_at is not None
            assert db.get(Device, UUID(identity_two.device_id)).last_seen_at is not None
            first_telemetry = db.get(DeviceTelemetryLatest, UUID(identity_one.device_id))
            second_telemetry = db.get(DeviceTelemetryLatest, UUID(identity_two.device_id))
            assert first_telemetry and second_telemetry
            assert first_telemetry.hostname == "WS-PC-01" and second_telemetry.hostname == "WS-PC-02"
            assert len(db.scalars(select(TelemetrySample).where(TelemetrySample.device_id == UUID(identity_one.device_id))).all()) == 1
        assert first_state == "ONLINE"
        assert second_state == "OFFLINE"

        # A malformed telemetry body is rejected without closing the authenticated heartbeat session.
        invalid = await submit_telemetry(agent_one, ws_one, "WS-PC-01", {"unexpected": "field"})
        assert invalid["payload"]["accepted"] is False
        assert invalid["payload"]["reason"] == "invalid_telemetry"
        assert (await agent_one.heartbeat(ws_one))["payload"]["accepted"] is True

        # A fresh signed ticket and increasing persisted sequence allow reconnect to restore ONLINE.
        ws_two_again = await agent_two.connect_once()
        await agent_two.heartbeat(ws_two_again)
        with server_app.state.session_factory() as db:
            assert db.get(DeviceStatus, UUID(identity_two.device_id)).agent_state == "ONLINE"
            transitions = db.scalars(select(DeviceStatusEvent).where(DeviceStatusEvent.device_id == UUID(identity_two.device_id))).all()
            assert {row.new_state for row in transitions} >= {"ONLINE", "OFFLINE"}

        csrf = login(client)
        session_cookie = client.cookies.get("labguard_session")
        def revoke_on_running_server():
            request = urllib.request.Request(f"{base_url}/api/v1/devices/{identity_two.device_id}/credential/revoke",
                data=b"", headers={"Cookie": f"labguard_session={session_cookie}", "X-CSRF-Token": csrf}, method="POST")
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()
        revoke_status, revoke_body = await asyncio.to_thread(revoke_on_running_server)
        assert revoke_status == 200 and b'"revoked":true' in revoke_body
        from websockets.exceptions import ConnectionClosed
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(ws_two_again.recv(), 2)
        assert ws_two_again.close_code == 4401
        with server_app.state.session_factory() as db:
            assert db.get(DeviceStatus, UUID(identity_two.device_id)).agent_state == "QUARANTINED"
        with pytest.raises(RuntimeError, match=r"Server rejected request \(401\)"):
            await asyncio.to_thread(agent_two._ticket)

        # A different UUID inside an authenticated message cannot change ticket identity.
        spoof_ws = await agent_one.connect_once()
        spoof = agent_one._envelope("client.telemetry", telemetry_payload("spoof"))
        spoof["device_id"] = identity_two.device_id
        await spoof_ws.send(json.dumps(spoof))
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(spoof_ws.recv(), 2)
        assert spoof_ws.close_code == 4401

        # Broken telemetry collection is isolated; normal heartbeat liveness continues.
        failing_agent = AgentClient(base_url, identity_three, heartbeat_interval=0.1, telemetry_interval_seconds=10,
                                    allow_insecure_dev=True)
        def fail_collection():
            raise OSError("system metrics unavailable")
        monkeypatch.setattr("labguard_client.agent.collect_system_telemetry", fail_collection)
        stop = asyncio.Event()
        running = asyncio.create_task(failing_agent.run_forever(stop))
        await asyncio.sleep(0.45)
        stop.set()
        await asyncio.wait_for(running, 2)
        with server_app.state.session_factory() as db:
            assert db.get(DeviceStatus, UUID(identity_three.device_id)).agent_state == "ONLINE"
        await ws_one.close()

    try:
        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()
