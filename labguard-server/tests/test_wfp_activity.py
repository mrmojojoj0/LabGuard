from datetime import UTC, datetime
from uuid import UUID, uuid4

from labguard_server.models import DeviceStatus, DeviceWfpEvent
from labguard_server.schemas import WfpEventBatchIn
from labguard_server.wfp_activity import record_wfp_batch
from tests.test_telemetry import approved_device
from tests.conftest import login


def event(record_id, event_id=5156, remote="8.8.8.8"):
    kind = {5152: "PACKET_BLOCKED", 5156: "CONNECTION_ALLOWED", 5157: "CONNECTION_BLOCKED"}[event_id]
    return {"event_record_id": record_id, "event_id": event_id,
        "event_time": datetime.now(UTC).isoformat(), "event_kind": kind,
        "direction": "OUTGOING", "protocol": "TCP", "protocol_number": 6,
        "source_ip": "192.168.1.10", "source_port": 50000,
        "destination_ip": remote, "destination_port": 443,
        "process_id": 4321, "process_path": r"C:\Windows\curl.exe"}


def batch(generation, records, cursor=None, status="ACTIVE", gap_reason=None):
    ids = [row["event_record_id"] for row in records]
    return WfpEventBatchIn.model_validate({
        "log_generation": str(generation), "cursor_record_id": cursor if cursor is not None else (ids[-1] if ids else 1),
        "status": status, "gap_reason": gap_reason, "events": records,
    })


def test_wfp_ingestion_deduplicates_and_exposes_paginated_public_events(client):
    identity = approved_device(client, "WFP-01")
    device_id = UUID(identity.device_id)
    generation = uuid4()
    factory = client.app.state.session_factory
    with factory() as db:
        row = db.get(DeviceStatus, device_id)
        accepted, result = record_wfp_batch(db, device_id, row.last_sequence + 1,
                                             batch(generation, [event(100), event(105, 5157)]))
        assert accepted and result["inserted"] == 2
        row = db.get(DeviceStatus, device_id)
        accepted, result = record_wfp_batch(db, device_id, row.last_sequence + 1,
                                             batch(generation, [event(100)]))
        assert accepted and result["inserted"] == 0
        assert db.query(DeviceWfpEvent).filter(DeviceWfpEvent.device_id == device_id).count() == 2

    login(client)
    response = client.get("/api/v1/network/events?limit=1&show_full_info=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2 and len(payload["events"]) == 1
    assert payload["events"][0]["source"] == "WFP_EVENT"
    assert payload["events"][0]["remote_ip"] == "8.8.8.8"
    assert payload["monitoring"][0]["status"] == "ACTIVE"


def test_default_wfp_endpoint_hides_private_remote_addresses(client):
    identity = approved_device(client, "WFP-PRIVATE")
    device_id = UUID(identity.device_id)
    with client.app.state.session_factory() as db:
        row = db.get(DeviceStatus, device_id)
        record_wfp_batch(db, device_id, row.last_sequence + 1,
            batch(uuid4(), [event(1, remote="10.1.2.3")]))
    login(client)
    response = client.get("/api/v1/network/events")
    assert response.status_code == 200
    assert response.json()["events"] == []
    full = client.get("/api/v1/network/events?show_full_info=true")
    assert full.status_code == 200 and full.json()["events"][0]["remote_ip"] == "10.1.2.3"
