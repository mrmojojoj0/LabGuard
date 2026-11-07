from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from labguard_client.identity import DeviceIdentity
from labguard_server.models import (AuditEvent, Device, DeviceTicket, SoftwareInventoryCollection,
    SoftwareInventoryItem, now_utc)
from labguard_server.schemas import SoftwareInventoryBatchIn, SoftwareInventoryEntryIn
from labguard_server.security import digest
from labguard_server.software_inventory import (device_software_items, global_software_list,
    inventory_status, record_software_inventory_batch, software_summary)
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


def entry(name, version="1.0", publisher="Publisher", *, source="WINDOWS_REGISTRY", scope="MACHINE",
          discovery_sources=None, package_id=None):
    key = hashlib.sha256(f"{name.lower()}|{publisher.lower()}|{scope}".encode()).hexdigest()
    return SoftwareInventoryEntryIn(entry_key=key, name=name, version=version, publisher=publisher,
        architecture="x64", install_date="2025-01-30", install_location="C:\\Program Files\\App",
        package_id=package_id, source=source, discovery_sources=discovery_sources or [], installation_scope=scope)


def batch(collection_id, index, count, entries, status="COMPLETE", *, digest_value="a" * 64,
          unchanged=False, request_id=None, errors=None):
    return SoftwareInventoryBatchIn(collection_id=collection_id, request_id=request_id, inventory_version=1,
        started_at=datetime.now(UTC), batch_index=index, batch_count=count, collection_status=status,
        inventory_digest=digest_value, unchanged=unchanged, entries=entries, errors=errors or [])


def submit(client, device_id, sequence, payload):
    with client.app.state.session_factory() as db:
        return record_software_inventory_batch(db, device_id, sequence, payload, 0, 90)


def test_inventory_persists_updates_changed_versions_batches_and_disappearance(client):
    device_id, _ = enroll(client, "INVENTORY-PC")
    app = entry("Example Editor")
    other = entry("Archive Tool", source="CHOCO")
    collection_id = uuid4()
    result, completed = submit(client, device_id, 1, batch(collection_id, 0, 2, [app]))
    assert result["accepted"] and not completed
    result, completed = submit(client, device_id, 2, batch(collection_id, 1, 2, [other]))
    assert result["accepted"] and completed and result["status"] == "COMPLETE"

    changed = entry("Example Editor", "2.0")
    next_id = uuid4()
    result, completed = submit(client, device_id, 3, batch(next_id, 0, 1, [changed]))
    assert completed
    with client.app.state.session_factory() as db:
        rows = db.scalars(select(SoftwareInventoryItem).where(SoftwareInventoryItem.device_id == device_id)).all()
        editor = next(row for row in rows if row.name == "Example Editor")
        archive = next(row for row in rows if row.name == "Archive Tool")
        assert len(rows) == 2
        assert editor.version == "2.0" and editor.first_seen_at is not None
        assert archive.is_present is False and archive.missing_since is not None

    partial_id = uuid4()
    result, completed = submit(client, device_id, 4, batch(partial_id, 0, 1, [changed], "PARTIAL", errors=["registry_access_denied:loaded_user_hives"]))
    assert completed and result["status"] == "PARTIAL"
    with client.app.state.session_factory() as db:
        archive = db.scalar(select(SoftwareInventoryItem).where(SoftwareInventoryItem.device_id == device_id,
            SoftwareInventoryItem.name == "Archive Tool"))
        assert archive.is_present is False
        status = inventory_status(db, device_id)
        assert status["status"] == "PARTIAL"
        assert status["last_successful_at"] is not None
        assert status["last_complete_at"] is not None
        assert status["last_attempt_status"] == "PARTIAL"
        assert status["last_attempt_at"] is not None
        assert status["stale"] is False
        summary = software_summary(db)
        assert summary["devices_with_successful_inventory"] == 1
        assert summary["partial_devices"] == 1
        assert summary["stale_devices"] == 0
        old_success_at = now_utc() - timedelta(days=8)
        for collection in db.scalars(select(SoftwareInventoryCollection).where(
                SoftwareInventoryCollection.device_id == device_id,
                SoftwareInventoryCollection.status.in_(("COMPLETE", "PARTIAL", "UNCHANGED")))):
            collection.completed_at = old_success_at
        db.commit()
        stale_status = inventory_status(db, device_id, stale_after_seconds=7 * 24 * 60 * 60)
        assert stale_status["status"] == "PARTIAL"
        assert stale_status["last_successful_at"] is not None
        assert stale_status["stale"] is True
        assert software_summary(db)["stale_devices"] == 1


def test_unchanged_report_refreshes_health_without_resending_items(client):
    device_id, _ = enroll(client, "UNCHANGED-PC")
    app = entry("Example Editor")
    first_id = uuid4()
    submit(client, device_id, 1, batch(first_id, 0, 1, [app], digest_value="b" * 64))
    unchanged = batch(uuid4(), 0, 1, [], digest_value="b" * 64, unchanged=True)
    result, completed = submit(client, device_id, 2, unchanged)
    assert completed and result["status"] == "UNCHANGED"
    with client.app.state.session_factory() as db:
        rows = db.scalars(select(SoftwareInventoryItem).where(SoftwareInventoryItem.device_id == device_id)).all()
        assert len(rows) == 1
        assert inventory_status(db, device_id)["status"] == "UNCHANGED"
        assert db.scalar(select(SoftwareInventoryCollection).where(SoftwareInventoryCollection.device_id == device_id,
            SoftwareInventoryCollection.status == "UNCHANGED")) is not None


def test_inventory_source_provenance_survives_database_and_api_serialization(client):
    device_id, _ = enroll(client, "INVENTORY-SOURCE-PC")
    item = entry("Mozilla Firefox", source="WINGET", package_id="Mozilla.Firefox",
        discovery_sources=["WINDOWS_REGISTRY", "WINGET"])
    submit(client, device_id, 1, batch(uuid4(), 0, 1, [item]))
    with client.app.state.session_factory() as db:
        results, count = device_software_items(db, device_id)
        assert count == 1
        assert results[0]["source"] == "WINGET"
        assert results[0]["discovery_sources"] == ["WINDOWS_REGISTRY", "WINGET"]
        row = db.scalar(select(SoftwareInventoryItem).where(SoftwareInventoryItem.device_id == device_id))
        assert row is not None and row.discovery_sources == ["WINDOWS_REGISTRY", "WINGET"]


def test_inventory_ingest_throttle_returns_retry_time_separate_from_refresh_cooldown(client):
    device_id, _ = enroll(client, "INVENTORY-RATE-LIMIT-PC")
    with client.app.state.session_factory() as db:
        first, completed = record_software_inventory_batch(
            db, device_id, 1, batch(uuid4(), 0, 1, [entry("First scan")]), 10, 90)
    assert first["accepted"] and completed

    with client.app.state.session_factory() as db:
        limited, completed = record_software_inventory_batch(
            db, device_id, 2, batch(uuid4(), 0, 1, [entry("Retry scan")]), 10, 90)

    assert not completed
    assert limited["accepted"] is False
    assert limited["reason"] == "inventory_rate_limited"
    assert 1 <= limited["retry_after_seconds"] <= 10


def test_inventory_min_interval_setting_is_bounded():
    from labguard_server.config import Settings

    base = {"database_url": "sqlite:///labguard.db", "session_secret": "s" * 32}
    Settings(**base, software_inventory_min_interval_seconds=10).validate()
    for value in (0, 61):
        with pytest.raises(RuntimeError, match="Software inventory cooldown"):
            Settings(**base, software_inventory_min_interval_seconds=value).validate()


def test_chocolatey_source_accepts_http_and_https_but_rejects_other_schemes():
    from labguard_server.config import Settings

    base = {"database_url": "sqlite:///labguard.db", "session_secret": "s" * 32}
    for scheme in ("http", "https"):
        Settings(**base, chocolatey_source_url=f"{scheme}://packages.example.test/choco").validate()
    with pytest.raises(RuntimeError, match="HTTP or HTTPS"):
        Settings(**base, chocolatey_source_url="ftp://packages.example.test/choco").validate()


def test_inventory_validation_authentication_and_filter_pagination(client):
    device_id, _ = enroll(client, "API-INVENTORY-PC")
    with pytest.raises(ValidationError):
        SoftwareInventoryEntryIn(entry_key="bad", name="Bad", architecture="x64", source="REGISTRY",
                                 installation_scope="MACHINE")
    with pytest.raises(HTTPException) as unauthorized:
        with client.app.state.session_factory() as db:
            record_software_inventory_batch(db, uuid4(), 1, batch(uuid4(), 0, 1, [entry("Test")]), 300, 90)
    assert unauthorized.value.status_code == 401
    submit(client, device_id, 1, batch(uuid4(), 0, 1, [entry("Editor"), entry("Viewer")]))
    csrf = login(client, "viewer", "viewer-password-123")
    response = client.get("/api/v1/devices/" + str(device_id) + "/software?search=Editor&limit=1")
    assert response.status_code == 200
    assert response.json()["total"] == 1 and response.json()["items"][0]["name"] == "Editor"
    global_response = client.get("/api/v1/software?publisher=Publisher&offset=0&limit=1")
    assert global_response.status_code == 200 and global_response.json()["total"] == 2
    summary = client.get("/api/v1/software/summary")
    assert summary.status_code == 200 and summary.json()["total_installations"] == 2
    assert client.delete(f"/api/v1/devices/{device_id}", headers={"X-CSRF-Token": csrf}).status_code == 403


def test_manual_refresh_requires_lab_admin_online_device_and_applies_cooldown(client, monkeypatch):
    device_id, _ = enroll(client, "REFRESH-PC")
    viewer_csrf = login(client, "viewer", "viewer-password-123")
    forbidden = client.post(f"/api/v1/devices/{device_id}/software/refresh",
        headers={"X-CSRF-Token": viewer_csrf})
    assert forbidden.status_code == 403
    csrf = login(client)
    offline = client.post(f"/api/v1/devices/{device_id}/software/refresh", headers={"X-CSRF-Token": csrf})
    assert offline.status_code == 409
    assert offline.json()["error"]["code"] == "device_offline"
    client.app.state.active_devices[device_id] = object()
    async def accept_refresh(_application, _device_id, _request_id):
        return True
    monkeypatch.setattr("labguard_server.api.request_software_inventory_refresh", accept_refresh)
    accepted = client.post(f"/api/v1/devices/{device_id}/software/refresh",
        headers={"X-CSRF-Token": csrf})
    assert accepted.status_code == 202 and accepted.json()["status"] == "requested"
    limited = client.post(f"/api/v1/devices/{device_id}/software/refresh",
        headers={"X-CSRF-Token": csrf})
    assert limited.status_code == 429
    with client.app.state.session_factory() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "software.inventory_refresh")).all()
        assert len(events) == 1 and events[0].target_id == str(device_id)


def test_collection_batches_reject_mismatched_metadata_and_digest(client):
    device_id, _ = enroll(client, "BATCH-PC")
    collection_id = uuid4()
    submit(client, device_id, 1, batch(collection_id, 0, 2, [entry("One")]))
    result, completed = submit(client, device_id, 2, batch(collection_id, 1, 2, [entry("Two")], digest_value="c" * 64))
    assert not completed and not result["accepted"]
    with client.app.state.session_factory() as db:
        collection = db.get(SoftwareInventoryCollection, collection_id)
        assert collection.status == "IN_PROGRESS" and collection.received_batches == 1


def test_agent_cannot_forge_manual_refresh_request_id(client):
    device_id, _ = enroll(client, "FORGED-REFRESH-PC")
    ticket = "inventory-ticket-for-test"
    with client.app.state.session_factory.begin() as db:
        db.add(DeviceTicket(device_id=device_id, token_hash=digest(ticket),
            expires_at=now_utc() + timedelta(minutes=1)))
    with client.websocket_connect("/api/v1/agent/session",
            headers={"Authorization": f"Bearer {ticket}"}) as socket:
        socket.send_json({"protocol": "labguard.agent", "schema_version": 1,
            "event_id": str(uuid4()), "device_id": str(device_id), "sequence": 1,
            "sent_at": datetime.now(UTC).isoformat(), "type": "client.hello",
            "payload": {"agent_version": "test", "boot_id": "test-boot"}})
        assert socket.receive_json()["type"] == "server.welcome"
        assert socket.receive_json()["type"] == "server.ack"
        forged = batch(uuid4(), 0, 1, [entry("Forged")], request_id=uuid4())
        socket.send_json({"protocol": "labguard.agent", "schema_version": 1,
            "event_id": str(uuid4()), "device_id": str(device_id), "sequence": 2,
            "sent_at": datetime.now(UTC).isoformat(), "type": "client.software_inventory",
            "payload": forged.model_dump(mode="json")})
        ack = socket.receive_json()
        assert ack["payload"]["accepted"] is False
        assert ack["payload"]["reason"] == "invalid_refresh_request"
    with client.app.state.session_factory() as db:
        assert db.scalar(select(SoftwareInventoryCollection).where(
            SoftwareInventoryCollection.device_id == device_id)) is None
