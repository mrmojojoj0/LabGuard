from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from labguard_server.models import Device, DeviceStatus, DeviceTelemetryLatest, TelemetrySample
from labguard_server.schemas import TelemetrySnapshotIn
from labguard_server.telemetry import latest_telemetry, record_telemetry, telemetry_history, telemetry_summary
from tests.conftest import login


def snapshot(hostname="TELEMETRY-PC"):
    return TelemetrySnapshotIn.model_validate({
        "collected_at": datetime.now(UTC).isoformat(),
        "cpu": {"processor_name": "Test CPU", "logical_processors": 8, "physical_cores": 4, "utilization_percent": 28.5},
        "memory": {"total_bytes": 16_000_000_000, "used_bytes": 8_000_000_000,
                   "available_bytes": 8_000_000_000, "utilization_percent": 50.0},
        "storage_partitions": [{"device": "C:", "mountpoint": "C:\\", "filesystem": "NTFS",
                                 "total_bytes": 1000, "used_bytes": 400, "free_bytes": 600, "utilization_percent": 40.0}],
        "operating_system": {"edition": "Windows Test", "version": "10.0", "build_number": "22631",
                             "architecture": "AMD64", "hostname": hostname},
        "boot_time": (datetime.now(UTC) - timedelta(hours=4)).isoformat(),
        "uptime_seconds": 14400,
        "network_interfaces": [{"name": "Ethernet", "status": "UP", "mac_address": "00:11:22:33:44:55",
                                 "ipv4_addresses": ["192.0.2.10"], "ipv6_addresses": ["2001:db8::10"], "speed_mbps": 1000}],
    })


def approved_device(client, name):
    from labguard_client.identity import DeviceIdentity

    identity = DeviceIdentity.ephemeral()
    csrf = login(client)
    code = client.post("/api/v1/enrollment-codes", headers={"X-CSRF-Token": csrf}).json()["code"]
    response = client.post("/api/v1/enrollment/request", json={"enrollment_code": code, "device_id": identity.device_id,
        "public_key": identity.public_key_pem(), "hostname": name})
    assert response.status_code == 201
    approved = client.post(f"/api/v1/enrollment/requests/{identity.device_id}/approve",
        json={"assigned_name": name}, headers={"X-CSRF-Token": csrf})
    assert approved.status_code == 200
    return identity


def test_invalid_telemetry_payload_is_rejected():
    value = snapshot().model_dump(mode="json")
    value["cpu"]["utilization_percent"] = 101
    with pytest.raises(ValidationError):
        TelemetrySnapshotIn.model_validate(value)
    value = snapshot().model_dump(mode="json")
    value["unexpected_admin_flag"] = True
    with pytest.raises(ValidationError):
        TelemetrySnapshotIn.model_validate(value)


def test_latest_history_summary_auth_and_staleness(client):
    identity = approved_device(client, "TELEMETRY-01")
    device_id = UUID(identity.device_id)
    factory = client.app.state.session_factory
    with factory() as db:
        device = db.get(Device, device_id)
        status = db.get(DeviceStatus, device_id)
        assert device and status
        received, reason = record_telemetry(db, device_id, status.last_sequence + 1, snapshot(device.hostname), 0, 30)
        assert received is not None and reason is None
        status = db.get(DeviceStatus, device_id)
        received2, reason = record_telemetry(db, device_id, status.last_sequence + 1, snapshot(device.hostname), 0, 30)
        assert received2 is not None and reason is None
        latest = db.get(DeviceTelemetryLatest, device_id)
        assert latest.received_at >= latest.collected_at
        rows = db.query(TelemetrySample).filter(TelemetrySample.device_id == device_id).all()
        assert len(rows) == 2
        latest.received_at = datetime.now(UTC) - timedelta(seconds=180)
        db.commit()
        result = latest_telemetry(db, device_id, 120)
        assert result["stale"] is True
        assert result["snapshot"]["cpu"]["utilization_percent"] == 28.5
        assert len(telemetry_history(db, device_id, 10, 30)) == 2
        assert telemetry_summary(db, 120)["stale_devices"] == 1

    client.cookies.clear()
    assert client.get(f"/api/v1/devices/{device_id}/telemetry").status_code == 401
    login(client)
    latest_response = client.get(f"/api/v1/devices/{device_id}/telemetry")
    assert latest_response.status_code == 200 and latest_response.json()["stale"] is True
    history_response = client.get(f"/api/v1/devices/{device_id}/telemetry/history?limit=10")
    assert history_response.status_code == 200 and len(history_response.json()["samples"]) == 2
    assert client.get("/api/v1/telemetry/summary").status_code == 200


def test_revoked_or_unapproved_device_cannot_persist_telemetry(client):
    identity = approved_device(client, "TELEMETRY-REVOKED")
    device_id = UUID(identity.device_id)
    factory = client.app.state.session_factory
    with factory.begin() as db:
        device = db.get(Device, device_id)
        device.enabled = False
    with factory() as db:
        status = db.get(DeviceStatus, device_id)
        with pytest.raises(HTTPException) as error:
            record_telemetry(db, device_id, status.last_sequence + 1, snapshot(), 0, 30)
        assert error.value.status_code == 401
        assert db.get(DeviceTelemetryLatest, device_id) is None
