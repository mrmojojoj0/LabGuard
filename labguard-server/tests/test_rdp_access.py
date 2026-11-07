from uuid import UUID

import pytest
from sqlalchemy import select

from labguard_server.models import (AuditEvent, DeviceStatus, RdpAccessRequest)
from labguard_server.rdp_access import create_rdp_access_request, hostname_is_safe, record_rdp_access_result
from labguard_server.schemas import RdpAccessResultIn
from tests.conftest import login


class FakeAgentSocket:
    def __init__(self, app):
        self.app = app
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


def enroll_approved_device(client, hostname="RDP-LAB-PC"):
    from labguard_client.identity import DeviceIdentity

    identity = DeviceIdentity.ephemeral()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    code = client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    response = client.post("/api/v1/enrollment/request", json={
        "enrollment_code": code, "device_id": identity.device_id,
        "public_key": identity.public_key_pem(), "hostname": hostname,
    })
    assert response.status_code == 201, response.text
    approved = client.post(f"/api/v1/enrollment/requests/{identity.device_id}/approve",
                           json={"assigned_name": hostname}, headers=headers)
    assert approved.status_code == 200, approved.text
    return identity, csrf


def test_hostname_validation_rejects_rdp_file_injection():
    assert hostname_is_safe("LAB-PC-01")
    assert hostname_is_safe("pc-01.example.edu")
    assert not hostname_is_safe("pc-01\r\nredirectdrives:i:1")
    assert not hostname_is_safe("/\\evil")


def test_admin_rdp_request_is_audited_and_sent_to_authenticated_device(client):
    identity, csrf = enroll_approved_device(client)
    device_id = UUID(identity.device_id)
    with client.app.state.session_factory.begin() as db:
        db.get(DeviceStatus, device_id).agent_state = "ONLINE"
    socket = FakeAgentSocket(client.app)
    client.app.state.active_devices[device_id] = socket

    response = client.post(f"/api/v1/devices/{device_id}/rdp/requests", headers={"X-CSRF-Token": csrf}, json={})
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["status"] == "PENDING"
    assert created["hostname"] == "RDP-LAB-PC"
    assert socket.messages[0]["type"] == "server.rdp.access.request"
    assert socket.messages[0]["payload"]["request_id"] == created["id"]
    assert socket.messages[0]["payload"]["access_expires_at"] == created["access_expires_at"]
    with client.app.state.session_factory() as db:
        audit_row = db.scalar(select(AuditEvent).where(AuditEvent.action == "rdp.access.requested"))
        assert audit_row is not None
        assert audit_row.actor_type == "ADMIN"
        assert audit_row.target_id == created["id"]

    status = client.get(f"/api/v1/devices/{device_id}/rdp/requests/{created['id']}")
    assert status.status_code == 200 and status.json()["status"] == "PENDING"


def test_rdp_request_rejects_offline_untrusted_and_non_admin_targets(client):
    identity, csrf = enroll_approved_device(client)
    device_id = UUID(identity.device_id)
    offline = client.post(f"/api/v1/devices/{device_id}/rdp/requests", headers={"X-CSRF-Token": csrf}, json={})
    assert offline.status_code == 409 and offline.json()["error"]["code"] == "device_offline"

    socket = FakeAgentSocket(client.app)
    client.app.state.active_devices[device_id] = socket
    with client.app.state.session_factory.begin() as db:
        db.get(DeviceStatus, device_id).agent_state = "ONLINE"
        from labguard_server.models import Device
        db.get(Device, device_id).hostname = "host\r\nredirectdrives:i:1"
    unsafe = client.post(f"/api/v1/devices/{device_id}/rdp/requests", headers={"X-CSRF-Token": csrf}, json={})
    assert unsafe.status_code == 409 and unsafe.json()["error"]["code"] == "rdp_hostname_unavailable"

    viewer_csrf = login(client, "viewer", "viewer-password-123")
    denied = client.post(f"/api/v1/devices/{device_id}/rdp/requests",
                         headers={"X-CSRF-Token": viewer_csrf}, json={})
    assert denied.status_code == 403


def test_agent_rdp_result_is_device_bound_sequenced_and_audited(client):
    identity, _csrf = enroll_approved_device(client)
    device_id = UUID(identity.device_id)
    with client.app.state.session_factory.begin() as db:
        status = db.get(DeviceStatus, device_id)
        status.agent_state = "ONLINE"
    with client.app.state.session_factory() as db:
        request = create_rdp_access_request(db, device_id, UUID(client.get("/api/v1/auth/me").json()["id"]))
        request_id = request.id
    with client.app.state.session_factory() as db:
        result = record_rdp_access_result(db, device_id, 1,
            RdpAccessResultIn(request_id=request_id, status="READY"))
        assert result == {"accepted": True, "status": "READY", "request_id": str(request_id)}
        assert db.get(RdpAccessRequest, request_id).status == "READY"
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "rdp.access.prepared"))
        assert event is not None and event.actor_type == "DEVICE"
    with client.app.state.session_factory() as db:
        replay = record_rdp_access_result(db, device_id, 1,
            RdpAccessResultIn(request_id=request_id, status="READY"))
        assert replay == {"accepted": False, "reason": "replayed_sequence"}


def test_only_one_pending_rdp_request_per_device(client):
    identity, _csrf = enroll_approved_device(client)
    device_id = UUID(identity.device_id)
    with client.app.state.session_factory.begin() as db:
        db.get(DeviceStatus, device_id).agent_state = "ONLINE"
    with client.app.state.session_factory() as db:
        from labguard_server.models import Administrator
        admin_id = db.scalar(select(Administrator.id).where(Administrator.username == "admin"))
        create_rdp_access_request(db, device_id, admin_id)
        with pytest.raises(Exception) as raised:
            create_rdp_access_request(db, device_id, admin_id)
        assert getattr(raised.value, "status_code", None) == 409
