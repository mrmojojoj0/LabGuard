from uuid import uuid4
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.conftest import login


def public_key_pem():
    return Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def test_authentication_and_session_revocation(client):
    bad = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    csrf = login(client)
    assert client.get("/api/v1/auth/me").json()["role"] == "SUPER_ADMIN"
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_authorization_and_csrf_enforced(client):
    csrf = login(client, "viewer", "viewer-password-123")
    response = client.post("/api/v1/rooms", json={"name": "Lab"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403
    login(client)
    response = client.post("/api/v1/rooms", json={"name": "Lab"})
    assert response.status_code == 403
    response = client.post("/api/v1/rooms", json={"name": "Lab"}, headers={"X-CSRF-Token": login(client)})
    assert response.status_code == 201


def test_enrollment_requires_code_and_admin_approval(client):
    csrf = login(client)
    code_response = client.post("/api/v1/enrollment-codes", headers={"X-CSRF-Token": csrf})
    assert code_response.status_code == 200
    code = code_response.json()["code"]
    device_id = str(uuid4())
    request = {"enrollment_code": code, "device_id": device_id, "public_key": public_key_pem(),
               "hostname": "LAB-01", "agent_version": "0.1"}
    submitted = client.post("/api/v1/enrollment/request", json=request)
    assert submitted.status_code == 201
    assert submitted.json()["enrollment_state"] == "PENDING"
    duplicate_code = client.post("/api/v1/enrollment/request", json={**request, "device_id": str(uuid4())})
    assert duplicate_code.status_code == 400
    denied = client.post(f"/api/v1/enrollment/requests/{device_id}/approve", json={"assigned_name": "LAB-PC-01"})
    assert denied.status_code == 403
    csrf = login(client)
    approved = client.post(f"/api/v1/enrollment/requests/{device_id}/approve", json={"assigned_name": "LAB-PC-01"},
                           headers={"X-CSRF-Token": csrf})
    assert approved.status_code == 200
    assert approved.json()["enrollment_state"] == "APPROVED"


def test_grid_conflict_bounds_and_audit(client):
    csrf = login(client)
    h = {"X-CSRF-Token": csrf}
    room = client.post("/api/v1/rooms", json={"name": "Lab", "grid_rows": 2, "grid_columns": 2}, headers=h).json()
    code = client.post("/api/v1/enrollment-codes", headers=h).json()["code"]
    ids = [str(uuid4()), str(uuid4())]
    for index, device_id in enumerate(ids):
        body = {"enrollment_code": code if index == 0 else client.post("/api/v1/enrollment-codes", headers=h).json()["code"],
                "device_id": device_id, "public_key": public_key_pem(), "hostname": f"PC-{index}"}
        assert client.post("/api/v1/enrollment/request", json=body).status_code == 201
        assert client.post(f"/api/v1/enrollment/requests/{device_id}/approve", json={"assigned_name": f"LAB-PC-{index+1:02}"}, headers=h).status_code == 200

    collision = client.put(f"/api/v1/rooms/{room['id']}/layout", headers=h,
                           json={"rows": 2, "columns": 2, "assignments":[{"device_id": ids[0], "row": 0, "column": 0},
                                                                              {"device_id": ids[1], "row": 0, "column": 0}]})
    assert collision.status_code == 422
    outside = client.put(f"/api/v1/rooms/{room['id']}/layout", headers=h,
                         json={"rows": 2, "columns": 2, "assignments":[{"device_id": ids[0], "row": 2, "column": 0}]})
    assert outside.status_code == 422
    placed = client.put(f"/api/v1/rooms/{room['id']}/layout", headers=h,
                        json={"rows": 2, "columns": 2, "assignments":[{"device_id": ids[0], "row": 0, "column": 0}]})
    assert placed.status_code == 200
    audit = client.get("/api/v1/audit-events")
    assert audit.status_code == 200
    assert {"room.create", "room.layout_update", "device.approve"}.issubset({x["action"] for x in audit.json()})


def test_room_crud_and_resize_cannot_orphan_positions(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    room = client.post("/api/v1/rooms", json={"name": "Small Lab", "grid_rows": 3, "grid_columns": 3}, headers=headers).json()
    device_id = str(uuid4())
    code = client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    assert client.post("/api/v1/enrollment/request", json={"enrollment_code": code, "device_id": device_id,
                    "public_key": public_key_pem(), "hostname": "PC-A"}).status_code == 201
    assert client.post(f"/api/v1/enrollment/requests/{device_id}/approve", json={"assigned_name": "PC-A"}, headers=headers).status_code == 200
    assert client.put(f"/api/v1/rooms/{room['id']}/layout", headers=headers,
                      json={"rows": 3, "columns": 3, "assignments":[{"device_id": device_id, "row": 2, "column": 2}]}).status_code == 200
    resized = client.patch(f"/api/v1/rooms/{room['id']}", headers=headers, json={"grid_rows": 2})
    assert resized.status_code == 409
    assert client.get(f"/api/v1/rooms/{room['id']}").status_code == 200
    archived = client.delete(f"/api/v1/rooms/{room['id']}", headers=headers)
    assert archived.status_code == 204
    assert client.get(f"/api/v1/rooms/{room['id']}").status_code == 404
