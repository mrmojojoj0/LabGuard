from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.conftest import login


def _device(client, headers, name="EXAM-PC-01"):
    room = client.post("/api/v1/rooms", headers=headers,
        json={"name": f"Exam Lab {uuid4().hex[:6]}", "grid_rows": 2, "grid_columns": 2}).json()
    device_id = str(uuid4())
    code = client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    key = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    assert client.post("/api/v1/enrollment/request", json={"enrollment_code": code,
        "device_id": device_id, "public_key": key, "hostname": name}).status_code == 201
    assert client.post(f"/api/v1/enrollment/requests/{device_id}/approve", headers=headers,
        json={"assigned_name": name}).status_code == 200
    assert client.put(f"/api/v1/rooms/{room['id']}/layout", headers=headers,
        json={"rows": 2, "columns": 2,
              "assignments": [{"device_id": device_id, "row": 0, "column": 0}]}).status_code == 200
    return room, device_id


def _exam_body(room_id, device_id, **overrides):
    starts = datetime.now(UTC) + timedelta(minutes=10)
    value = {"title": "Midterm exam", "room_id": room_id, "device_ids": [device_id],
        "starts_at": starts.isoformat(), "ends_at": (starts + timedelta(hours=1)).isoformat(),
        "policy": {"network_mode": "ALLOW_LIST", "allowed_networks": ["192.168.1.0/24"],
            "restricted_apps": ["game.exe"], "restrict_browsers": True,
            "block_usb_storage": True, "screenshot_on_violation": True}}
    return {**value, **overrides}


def test_exam_creation_schedule_and_report_reuse_lab_devices(client):
    headers = {"X-CSRF-Token": login(client)}
    room, device_id = _device(client, headers)
    response = client.post("/api/v1/exams", headers=headers, json=_exam_body(room["id"], device_id))
    assert response.status_code == 201, response.text
    exam = response.json()
    assert exam["status"] == "SCHEDULED"
    assert exam["device_ids"] == [device_id]
    assert exam["policy"]["allowed_networks"] == ["192.168.1.0/24"]
    assert exam["policy"]["restricted_browsers"] == ["msedge.exe", "chrome.exe", "firefox.exe"]
    assert client.get("/api/v1/exams").json()[0]["id"] == exam["id"]
    report = client.get(f"/api/v1/exams/{exam['id']}/report").json()
    assert report["devices"][0]["device_id"] == device_id
    assert report["violations"] == []
    assert client.post(f"/api/v1/exams/{exam['id']}/cancel", headers=headers).json()["status"] == "CANCELLED"


def test_exam_rejects_unassigned_targets_conflicts_and_invalid_policy(client):
    headers = {"X-CSRF-Token": login(client)}
    room, device_id = _device(client, headers)
    body = _exam_body(room["id"], device_id)
    assert client.post("/api/v1/exams", json=body).status_code == 403
    bad = _exam_body(room["id"], device_id, policy={"network_mode": "ALLOW_LIST", "allowed_networks": []})
    assert client.post("/api/v1/exams", headers=headers, json=bad).status_code == 422
    assert client.post("/api/v1/exams", headers=headers,
        json=_exam_body(str(uuid4()), device_id)).status_code == 404
    assert client.post("/api/v1/exams", headers=headers, json=body).status_code == 201
    assert client.post("/api/v1/exams", headers=headers, json=body).status_code == 409
