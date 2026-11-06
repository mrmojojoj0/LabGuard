from sqlalchemy import select

from labguard_server.models import AuditEvent, SoftwareCatalogPackage
from labguard_server.winget_discovery import WingetPackage


def login(client, username="admin", password="correct-horse-battery-staple"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_discovery_search_is_super_admin_only_and_returns_repository_results(client, monkeypatch):
    calls = []

    def search(query, source):
        calls.append((query, source))
        return "v1.9.0", [WingetPackage("Firefox", "Mozilla.Firefox", "132.0", source)]

    monkeypatch.setattr("labguard_server.api.search_winget_packages", search)
    viewer_csrf = login(client, "viewer", "viewer-password-123")
    denied = client.get("/api/v1/software/discovery/search?query=Firefox", headers={"X-CSRF-Token": viewer_csrf})
    assert denied.status_code == 403

    login(client)
    result = client.get("/api/v1/software/discovery/search?query=Firefox")
    assert result.status_code == 200
    assert result.json() == {
        "source": "winget", "winget_version": "v1.9.0",
        "results": [{"name": "Firefox", "package_id": "Mozilla.Firefox", "version": "132.0",
                     "source": "winget", "catalog_status": None}],
    }
    assert calls == [("Firefox", "winget")]


def test_discovery_import_adds_pending_catalog_entry_audits_and_deduplicates(client, monkeypatch):
    calls = []

    def metadata(package_id, source):
        calls.append((package_id, source))
        return {"display_name": "Mozilla Firefox", "publisher": "Mozilla", "description": "Web browser"}

    monkeypatch.setattr("labguard_server.api.get_winget_package_metadata", metadata)
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    body = {"package_id": "Mozilla.Firefox", "source": "winget", "supported_scopes": ["MACHINE"]}

    created = client.post("/api/v1/software/discovery/import", headers=headers, json=body)
    assert created.status_code == 201, created.text
    result = created.json()
    package = result["package"]
    assert result["created"] is True
    assert package["package_manager"] == "WINGET"
    assert package["approval_status"] == "PENDING" and package["approved"] is False
    assert package["publisher"] == "Mozilla"
    assert calls == [("Mozilla.Firefox", "winget")]

    duplicate = client.post("/api/v1/software/discovery/import", headers=headers, json=body)
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] is False
    assert duplicate.json()["package"]["id"] == package["id"]
    assert calls == [("Mozilla.Firefox", "winget")]
    with client.app.state.session_factory() as db:
        records = db.scalars(select(SoftwareCatalogPackage).where(
            SoftwareCatalogPackage.package_manager == "WINGET")).all()
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "software.catalog.discover"))
        assert len(records) == 1
        assert audit is not None and audit.target_id == package["id"]


def test_discovery_import_rejects_bad_package_id_before_calling_winget(client, monkeypatch):
    called = False

    def metadata(*_args):
        nonlocal called
        called = True
        raise AssertionError("invalid package ID must not reach WinGet")

    monkeypatch.setattr("labguard_server.api.get_winget_package_metadata", metadata)
    csrf = login(client)
    response = client.post("/api/v1/software/discovery/import", headers={"X-CSRF-Token": csrf}, json={
        "package_id": "../bad.exe", "source": "winget",
    })
    assert response.status_code == 422
    assert called is False
