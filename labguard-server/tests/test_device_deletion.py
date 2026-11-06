from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import select

from labguard_client.identity import DeviceIdentity
from labguard_server.models import (AuditEvent, Device, DeviceAuthChallenge, DeviceCredential,
    DevicePosition, DeviceStatus, DeviceStatusEvent, DeviceTelemetryLatest, DeviceTicket,
    Room, TelemetrySample, now_utc)
from labguard_server.security import digest
from tests.conftest import login


def enroll(client, name):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    code = client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    identity = DeviceIdentity.ephemeral()
    response = client.post("/api/v1/enrollment/request", json={"enrollment_code": code,
        "device_id": identity.device_id, "public_key": identity.public_key_pem(), "hostname": name})
    assert response.status_code == 201, response.text
    response = client.post(f"/api/v1/enrollment/requests/{identity.device_id}/approve",
        json={"assigned_name": name}, headers=headers)
    assert response.status_code == 200, response.text
    return UUID(identity.device_id), identity


def test_delete_device_revokes_identity_cascades_owned_data_and_preserves_audit(client):
    device_id, _identity = enroll(client, "DELETE-PC-01")
    other_id, _ = enroll(client, "KEEP-PC-02")
    admin_csrf = login(client)
    room = Room(name="Deletion Lab", grid_rows=2, grid_columns=3)
    now = now_utc()
    old_ticket = "already-issued-ticket"
    with client.app.state.session_factory.begin() as db:
        db.add(room)
        db.flush()
        db.add(DevicePosition(device_id=device_id, room_id=room.id, row_index=1, column_index=2))
        db.add(DeviceStatusEvent(device_id=device_id, previous_state="OFFLINE", new_state="ONLINE", reason="test"))
        db.add(DeviceAuthChallenge(device_id=device_id, nonce_hash="a" * 64, expires_at=now + timedelta(minutes=1)))
        db.add(DeviceTicket(device_id=device_id, token_hash=digest(old_ticket), expires_at=now + timedelta(minutes=1)))
        db.add(DeviceTelemetryLatest(device_id=device_id, collected_at=now, received_at=now,
            logical_processors=4, cpu_percent=10, memory_total_bytes=100, memory_used_bytes=50,
            memory_available_bytes=50, memory_percent=50, storage_partitions=[], architecture="x64",
            hostname="DELETE-PC-01", boot_time=now, uptime_seconds=10, network_interfaces=[]))
        db.add(TelemetrySample(device_id=device_id, collected_at=now, received_at=now, cpu_percent=10,
            memory_used_bytes=50, memory_total_bytes=100, memory_percent=50, disk_used_bytes=0,
            disk_total_bytes=0, disk_percent=None))
        db.add(AuditEvent(actor_type="ADMIN", action="device.review", target_type="device",
            target_id=str(device_id), result="SUCCESS", metadata_json="{}"))

    active_socket = AsyncMock()
    client.app.state.active_devices[device_id] = active_socket
    response = client.delete(f"/api/v1/devices/{device_id}", headers={"X-CSRF-Token": admin_csrf})
    assert response.status_code == 204, response.text
    active_socket.close.assert_awaited_once_with(code=4404, reason="device_deleted")
    assert device_id not in client.app.state.active_devices

    with client.app.state.session_factory() as db:
        assert db.get(Device, device_id) is None
        assert db.get(Device, other_id) is not None
        assert db.get(DeviceCredential, device_id) is None
        assert db.get(DeviceStatus, device_id) is None
        assert db.get(DevicePosition, device_id) is None
        assert db.scalar(select(DeviceAuthChallenge).where(DeviceAuthChallenge.device_id == device_id)) is None
        assert db.scalar(select(DeviceTicket).where(DeviceTicket.device_id == device_id)) is None
        assert db.scalar(select(DeviceTelemetryLatest).where(DeviceTelemetryLatest.device_id == device_id)) is None
        assert db.scalar(select(TelemetrySample).where(TelemetrySample.device_id == device_id)) is None
        assert db.scalar(select(DeviceStatusEvent).where(DeviceStatusEvent.device_id == device_id)) is None
        history = db.scalars(select(AuditEvent).where(AuditEvent.target_id == str(device_id))).all()
        assert {"device.review", "device.delete", "device.enrollment_requested", "device.approve"} <= {row.action for row in history}
        deletion = next(row for row in history if row.action == "device.delete")
        assert '"hostname":"DELETE-PC-01"' in deletion.metadata_json
        assert db.get(Room, room.id) is not None
    challenge = client.post("/api/v1/agent/challenge", json={"device_id": str(device_id)})
    assert challenge.status_code == 401
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect("/api/v1/agent/session", headers={"Authorization": f"Bearer {old_ticket}"}):
            pass
    assert disconnected.value.code == 4401


def test_device_delete_requires_role_and_csrf(client):
    device_id, _ = enroll(client, "ROLE-PC")
    admin_csrf = login(client)
    assert client.delete(f"/api/v1/devices/{device_id}").status_code == 403

    csrf = login(client, "viewer", "viewer-password-123")
    assert client.delete(f"/api/v1/devices/{device_id}", headers={"X-CSRF-Token": csrf}).status_code == 403

    with client.app.state.session_factory.begin() as db:
        from labguard_server.models import Administrator
        from labguard_server.security import hash_password
        db.add(Administrator(username="operator", password_hash=hash_password("operator-password-123"), role="OPERATOR"))
    csrf = login(client, "operator", "operator-password-123")
    assert client.delete(f"/api/v1/devices/{device_id}", headers={"X-CSRF-Token": csrf}).status_code == 403
    with client.app.state.session_factory() as db:
        assert db.get(Device, device_id) is not None


def test_delete_nonexistent_device_returns_not_found(client):
    csrf = login(client)
    response = client.delete("/api/v1/devices/11111111-1111-4111-8111-111111111111",
                            headers={"X-CSRF-Token": csrf})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_delete_closes_real_agent_websocket(client):
    device_id, _identity = enroll(client, "CONNECTED-PC")
    raw_ticket = "ticket-for-connected-test"
    with client.app.state.session_factory.begin() as db:
        db.add(DeviceTicket(device_id=device_id, token_hash=digest(raw_ticket),
            expires_at=now_utc() + timedelta(minutes=1)))
    csrf = login(client)
    with client.websocket_connect("/api/v1/agent/session", headers={"Authorization": f"Bearer {raw_ticket}"}) as socket:
        socket.send_json({"protocol": "labguard.agent", "schema_version": 1, "event_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "device_id": str(device_id), "sequence": 1, "sent_at": now_utc().isoformat(), "type": "client.hello",
            "payload": {"agent_version": "test", "boot_id": "test-boot"}})
        assert socket.receive_json()["type"] == "server.welcome"
        assert socket.receive_json()["type"] == "server.ack"
        response = client.delete(f"/api/v1/devices/{device_id}", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 204, response.text
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 4404
