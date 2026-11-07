import asyncio
from uuid import UUID

from alembic import command
from alembic.config import Config
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy import select

from labguard_client.identity import DeviceIdentity
from labguard_server.models import AuditEvent, SoftwareInventoryItem, SoftwareJob
from labguard_server.schemas import SoftwareJobEventIn
from labguard_server.software_jobs import dispatch_software_job, record_software_job_event
from tests.conftest import login


def test_software_jobs_migration_downgrade_and_upgrade_sqlite(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'migration.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(config, "head")
    command.downgrade(config, "0004_software_inventory")
    with create_engine(database_url).connect() as connection:
        tables = inspect(connection).get_table_names()
        assert "software_jobs" not in tables
        assert "software_catalog_packages" not in tables
        assert "job_id" not in {column["name"] for column in inspect(connection).get_columns("software_inventory_collections")}
    command.upgrade(config, "head")
    with create_engine(database_url).connect() as connection:
        assert "software_jobs" in inspect(connection).get_table_names()
        assert "job_id" in {column["name"] for column in inspect(connection).get_columns("software_inventory_collections")}
        assert "approval_status" in {column["name"] for column in inspect(connection).get_columns("software_catalog_packages")}
        assert "discovery_sources" in {column["name"] for column in inspect(connection).get_columns("software_inventory_items")}


def enrolled_device(client, name="SOFTWARE-JOBS-PC"):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    code = client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    identity = DeviceIdentity.ephemeral()
    request = client.post("/api/v1/enrollment/request", json={
        "enrollment_code": code, "device_id": identity.device_id,
        "public_key": identity.public_key_pem(), "hostname": name,
    })
    assert request.status_code == 201, request.text
    approved = client.post(f"/api/v1/enrollment/requests/{identity.device_id}/approve",
        json={"assigned_name": name}, headers=headers)
    assert approved.status_code == 200, approved.text
    return UUID(identity.device_id)


def approved_package(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post("/api/v1/software/catalog", headers=headers, json={
        "display_name": "Example Editor", "package_id": "Example.Editor",
        "package_manager": "WINGET", "publisher": "Example Corp",
        "version_policy": "LATEST", "supported_scopes": ["MACHINE"],
    })
    assert created.status_code == 201, created.text
    package_id = created.json()["id"]
    approved = client.post(f"/api/v1/software/catalog/{package_id}/approve", headers=headers)
    assert approved.status_code == 200 and approved.json()["approved"] is True
    return package_id


def test_catalog_review_authorization_and_queued_job_audit(client):
    device_id = enrolled_device(client)
    package_id = approved_package(client)

    viewer_csrf = login(client, "viewer", "viewer-password-123")
    forbidden = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": viewer_csrf}, json={
            "action": "INSTALL", "catalog_package_id": package_id,
            "installation_scope": "MACHINE",
        })
    assert forbidden.status_code == 403

    csrf = login(client)
    queued = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": csrf}, json={
            "action": "INSTALL", "catalog_package_id": package_id,
            "installation_scope": "MACHINE",
        })
    assert queued.status_code == 202, queued.text
    body = queued.json()
    assert body["device_id"] == str(device_id)
    assert body["status"] == "PENDING"  # offline target remains queued
    assert body["package_id"] == "Example.Editor"
    with client.app.state.session_factory() as db:
        persisted = db.get(SoftwareJob, UUID(body["id"]))
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "software.job_requested"))
        assert persisted is not None and audit is not None
        assert audit.target_id == body["id"]


def test_job_rejects_unapproved_package_and_invalid_identifiers(client):
    device_id = enrolled_device(client)
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    pending = client.post("/api/v1/software/catalog", headers=headers, json={
        "display_name": "Pending Package", "package_id": "Pending.Package",
        "package_manager": "WINGET", "version_policy": "LATEST",
        "supported_scopes": ["MACHINE"],
    })
    assert pending.status_code == 201
    viewer_csrf = login(client, "viewer", "viewer-password-123")
    viewer_catalog = client.get("/api/v1/software/catalog?approved=false",
        headers={"X-CSRF-Token": viewer_csrf})
    assert viewer_catalog.status_code == 200 and viewer_catalog.json() == []
    headers = {"X-CSRF-Token": login(client)}
    rejected = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers=headers, json={"action": "INSTALL", "catalog_package_id": pending.json()["id"]})
    assert rejected.status_code == 409

    invalid = client.post("/api/v1/software/catalog", headers=headers, json={
        "display_name": "Bad", "package_id": "../../setup.exe",
        "package_manager": "WINGET", "version_policy": "LATEST",
        "supported_scopes": ["MACHINE"],
    })
    assert invalid.status_code == 422


def test_uninstall_job_requires_authorization_and_exact_present_package(client):
    device_id = enrolled_device(client, "UNINSTALL-PC")
    package_id = approved_package(client)
    with client.app.state.session_factory() as db:
        item = SoftwareInventoryItem(device_id=device_id, entry_key="a" * 64, product_key="b" * 64,
            name="Example Editor", version="1.0", publisher="Example Corp", architecture="x64",
            install_date=None, install_location=None, package_id="Example.Editor", source="WINGET",
            discovery_sources=["WINGET", "WINDOWS_REGISTRY"], installation_scope="MACHINE",
            is_present=True, missing_since=None)
        db.add(item)
        db.commit()
        item_id = item.id
    viewer_csrf = login(client, "viewer", "viewer-password-123")
    denied = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": viewer_csrf}, json={"action": "UNINSTALL",
            "catalog_package_id": package_id, "inventory_item_id": str(item_id),
            "installation_scope": "MACHINE"})
    assert denied.status_code == 403
    csrf = login(client)
    accepted = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": csrf}, json={"action": "UNINSTALL",
            "catalog_package_id": package_id, "inventory_item_id": str(item_id),
            "installation_scope": "MACHINE"})
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["action"] == "UNINSTALL"
    assert accepted.json()["status"] == "PENDING"
    with client.app.state.session_factory() as db:
        job = db.get(SoftwareJob, UUID(accepted.json()["id"]))
        assert job is not None and job.package_id == "Example.Editor"
        assert job.installation_scope == "MACHINE"


def test_uninstall_rejects_unmatched_registry_item(client):
    device_id = enrolled_device(client, "UNINSTALL-UNSUPPORTED-PC")
    package_id = approved_package(client)
    with client.app.state.session_factory() as db:
        item = SoftwareInventoryItem(device_id=device_id, entry_key="c" * 64, product_key="d" * 64,
            name="Unknown Registry App", version="1.0", publisher=None, architecture="UNKNOWN",
            install_date=None, install_location=None, package_id=None, source="WINDOWS_REGISTRY",
            discovery_sources=["WINDOWS_REGISTRY"], installation_scope="MACHINE", is_present=True)
        db.add(item)
        db.commit()
        item_id = item.id
    csrf = login(client)
    response = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": csrf}, json={"action": "UNINSTALL",
            "catalog_package_id": package_id, "inventory_item_id": str(item_id),
            "installation_scope": "MACHINE"})
    assert response.status_code == 409
    assert "uninstall_unsupported" in response.text


def test_direct_winget_install_validates_identity_persists_audits_and_queues_offline(client, monkeypatch):
    device_id = enrolled_device(client, "DIRECT-WINGET-PC")
    monkeypatch.setattr("labguard_server.api.get_winget_package_metadata", lambda package_id, source, version=None: {
        "display_name": "Vendor Editor", "package_id": "Vendor.Editor", "version": "4.2.0",
        "publisher": "Vendor Inc", "description": None,
    })
    headers = {"X-CSRF-Token": login(client)}
    response = client.post(f"/api/v1/devices/{device_id}/software/jobs", headers=headers, json={
        "action": "INSTALL", "package_manager": "WINGET", "package_id": "Vendor.Editor",
        "source": "winget", "version": "4.2.0", "installation_scope": "MACHINE",
    })
    assert response.status_code == 202, response.text
    job_id = UUID(response.json()["id"])
    assert response.json()["status"] == "PENDING"
    assert response.json()["catalog_package_id"] is None
    with client.app.state.session_factory() as db:
        job = db.get(SoftwareJob, job_id)
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "software.job_requested"))
        assert job.package_id == "Vendor.Editor" and job.package_manager == "WINGET"
        assert job.source == "WINGET_COMMUNITY" and job.requested_version == "4.2.0"
        assert job.catalog_package_id is None and audit is not None


def test_direct_winget_install_rejects_invalid_source_identity_and_role(client, monkeypatch):
    device_id = enrolled_device(client, "DIRECT-WINGET-VALIDATION-PC")
    monkeypatch.setattr("labguard_server.api.get_winget_package_metadata", lambda *args: {
        "display_name": "Vendor Editor", "package_id": "Vendor.Editor", "version": "4.2.0",
        "publisher": "Vendor Inc", "description": None,
    })
    base = {"action": "INSTALL", "package_manager": "WINGET", "package_id": "Vendor.Editor",
            "source": "winget", "installation_scope": "MACHINE"}
    viewer = {"X-CSRF-Token": login(client, "viewer", "viewer-password-123")}
    forbidden = client.post(f"/api/v1/devices/{device_id}/software/jobs", headers=viewer, json=base)
    assert forbidden.status_code == 403
    headers = {"X-CSRF-Token": login(client)}
    invalid_source = client.post(f"/api/v1/devices/{device_id}/software/jobs", headers=headers,
        json={**base, "source": "msstore"})
    assert invalid_source.status_code == 422
    invalid_id = client.post(f"/api/v1/devices/{device_id}/software/jobs", headers=headers,
        json={**base, "package_id": "../bad.exe"})
    assert invalid_id.status_code == 422
    wrong_search_identity = client.post(f"/api/v1/devices/{device_id}/software/jobs", headers=headers,
        json={**base, "package_id": "Other.Package"})
    assert wrong_search_identity.status_code == 422
    assert client.post(f"/api/v1/devices/{device_id}/software/jobs", headers=headers,
        json={**base, "installation_scope": "SYSTEM"}).status_code == 422


def test_direct_uninstall_uses_exact_inventory_identity_without_catalog(client):
    device_id = enrolled_device(client, "DIRECT-UNINSTALL-PC")
    with client.app.state.session_factory() as db:
        item = SoftwareInventoryItem(device_id=device_id, entry_key="e" * 64, product_key="f" * 64,
            name="Example Editor", version="1.0", publisher="Vendor", architecture="x64",
            install_date=None, install_location=None, package_id="Example.Editor", source="WINGET",
            discovery_sources=["WINDOWS_REGISTRY", "WINGET"], installation_scope="MACHINE",
            is_present=True, missing_since=None)
        db.add(item)
        db.commit()
        item_id = item.id
    response = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": login(client)}, json={
            "action": "UNINSTALL", "inventory_item_id": str(item_id),
        })
    assert response.status_code == 202, response.text
    assert response.json()["package_id"] == "Example.Editor"
    assert response.json()["catalog_package_id"] is None

    with client.app.state.session_factory() as db:
        unknown_scope = SoftwareInventoryItem(device_id=device_id, entry_key="1" * 64, product_key="2" * 64,
            name="Unknown Scope App", version="1.0", publisher="Vendor", architecture="UNKNOWN",
            install_date=None, install_location=None, package_id="Vendor.Unknown", source="WINGET",
            discovery_sources=["WINGET"], installation_scope="UNKNOWN", is_present=True, missing_since=None)
        db.add(unknown_scope)
        db.commit()
        unknown_id = unknown_scope.id
    rejected = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": login(client)}, json={
            "action": "UNINSTALL", "inventory_item_id": str(unknown_id),
        })
    assert rejected.status_code == 409
    assert "uninstall_unsupported" in rejected.text


def test_catalog_mutations_require_super_admin_csrf(client):
    body = {"display_name": "Editor", "package_id": "Vendor.Editor",
        "package_manager": "WINGET", "version_policy": "LATEST", "supported_scopes": ["MACHINE"]}
    csrf = login(client)
    missing_csrf = client.post("/api/v1/software/catalog", json=body)
    assert missing_csrf.status_code == 403
    viewer_csrf = login(client, "viewer", "viewer-password-123")
    insufficient_role = client.post("/api/v1/software/catalog", json=body,
        headers={"X-CSRF-Token": viewer_csrf})
    assert insufficient_role.status_code == 403


def test_catalog_reject_approve_and_approved_visibility(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post("/api/v1/software/catalog", headers=headers, json={
        "display_name": "Reviewable Editor", "package_id": "Reviewable.Editor",
        "package_manager": "WINGET", "publisher": "Review Co", "description": "Editor description",
        "version_policy": "LATEST", "supported_scopes": ["MACHINE"],
    })
    assert created.status_code == 201, created.text
    package = created.json()
    assert package["approval_status"] == "PENDING"
    viewer_csrf = login(client, "viewer", "viewer-password-123")
    viewer_catalog = client.get("/api/v1/software/catalog", headers={"X-CSRF-Token": viewer_csrf})
    assert "Reviewable.Editor" not in [row["package_id"] for row in viewer_catalog.json()]
    headers = {"X-CSRF-Token": login(client)}

    rejected = client.post(f"/api/v1/software/catalog/{package['id']}/reject", headers=headers)
    assert rejected.status_code == 200 and rejected.json()["approval_status"] == "REJECTED"
    assert not rejected.json()["approved"]
    approved = client.post(f"/api/v1/software/catalog/{package['id']}/approve", headers=headers)
    assert approved.status_code == 200 and approved.json()["approval_status"] == "APPROVED"
    visible = client.get("/api/v1/software/catalog")
    assert any(row["id"] == package["id"] for row in visible.json())
    with client.app.state.session_factory() as db:
        rejected_audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "software.catalog.reject"))
        assert rejected_audit is not None


def test_job_event_lifecycle_progress_and_result_are_persisted(client):
    device_id = enrolled_device(client)
    package_id = approved_package(client)
    csrf = login(client)
    queued = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": csrf}, json={
            "action": "INSTALL", "catalog_package_id": package_id,
            "installation_scope": "MACHINE",
        })
    job_id = UUID(queued.json()["id"])
    with client.app.state.session_factory.begin() as db:
        db.get(SoftwareJob, job_id).status = "DISPATCHED"

    events = [
        (1, "client.job.accepted", {}),
        (2, "client.job.started", {}),
        (3, "client.job.progress", {"progress_percent": 55, "progress_message": "Installing"}),
        (4, "client.job.completed", {"result_code": "verified_success", "result_summary": "Installed and verified"}),
    ]
    for sequence, event_type, values in events:
        with client.app.state.session_factory() as db:
            result, terminal = record_software_job_event(db, device_id, sequence, event_type,
                SoftwareJobEventIn(job_id=job_id, **values))
        assert result["accepted"] is True
        if event_type == "client.job.completed":
            assert terminal is True
    with client.app.state.session_factory() as db:
        replay, _ = record_software_job_event(db, device_id, 4, "client.job.completed",
            SoftwareJobEventIn(job_id=job_id, result_code="verified_success"))
    assert replay["reason"] == "replayed_sequence"
    with client.app.state.session_factory() as db:
        completed = db.get(SoftwareJob, job_id)
        assert completed.status == "SUCCEEDED"
        assert completed.progress_percent == 100
        assert completed.result_code == "verified_success"
        assert completed.completed_at is not None


def test_pending_job_dispatch_and_reconnect_redelivery(client, monkeypatch):
    device_id = enrolled_device(client)
    package_id = approved_package(client)
    csrf = login(client)
    queued = client.post(f"/api/v1/devices/{device_id}/software/jobs",
        headers={"X-CSRF-Token": csrf}, json={
            "action": "INSTALL", "catalog_package_id": package_id,
            "installation_scope": "MACHINE",
        })
    job_id = UUID(queued.json()["id"])
    delivered = []

    async def send_offer(_app, target, payload):
        delivered.append((target, payload))
        return True

    monkeypatch.setattr("labguard_server.websocket.send_software_job_offer", send_offer)
    client.app.state.active_devices[device_id] = object()
    assert asyncio.run(dispatch_software_job(client.app, job_id)) is True
    assert asyncio.run(dispatch_software_job(client.app, job_id)) is True
    assert len(delivered) == 2
    assert delivered[0][0] == device_id
    assert delivered[0][1]["job_id"] == str(job_id)
    with client.app.state.session_factory() as db:
        job = db.get(SoftwareJob, job_id)
        assert job.status == "DISPATCHED"
        assert job.dispatched_at is not None
