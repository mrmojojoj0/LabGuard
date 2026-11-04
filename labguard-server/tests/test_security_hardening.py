import base64
import hashlib
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from labguard_client.identity import DeviceIdentity
from labguard_server.models import DeviceAuthChallenge, DeviceTicket, EnrollmentCode, now_utc
from labguard_server.security import digest
from labguard_server.services import claim_device_ticket
from tests.conftest import login


def _enroll(client, identity):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    code = client.post("/api/v1/enrollment-codes", headers=headers).json()["code"]
    response = client.post("/api/v1/enrollment/request", json={"enrollment_code": code,
        "device_id": identity.device_id, "public_key": identity.public_key_pem(), "hostname": "SECURITY-PC"})
    assert response.status_code == 201
    return headers


def _approve(client, identity, headers):
    return client.post(f"/api/v1/enrollment/requests/{identity.device_id}/approve",
        json={"assigned_name": "SECURITY-PC"}, headers=headers)


def _proof(identity, challenge):
    nonce_hash = hashlib.sha256(challenge["nonce"].encode("ascii")).hexdigest()
    message = f"labguard.device.auth.v1\n{identity.device_id}\n{challenge['challenge_id']}\n{nonce_hash}".encode("ascii")
    return base64.urlsafe_b64encode(identity.sign(message)).decode("ascii").rstrip("=")


def test_enrollment_codes_are_eight_easy_to_read_characters(client):
    csrf = login(client)
    response = client.post("/api/v1/enrollment-codes", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    code = response.json()["code"]
    assert len(code) == 8
    assert all(character in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for character in code)


def test_pending_device_and_invalid_signature_cannot_authenticate(client):
    identity = DeviceIdentity.ephemeral()
    headers = _enroll(client, identity)
    response = client.post("/api/v1/agent/challenge", json={"device_id": identity.device_id})
    assert response.status_code == 401
    assert _approve(client, identity, headers).status_code == 200
    challenge = client.post("/api/v1/agent/challenge", json={"device_id": identity.device_id}).json()
    invalid = base64.urlsafe_b64encode(b"x" * 64).decode("ascii").rstrip("=")
    rejected = client.post("/api/v1/agent/ticket", json={"device_id": identity.device_id,
        "challenge_id": challenge["challenge_id"], "signature": invalid})
    assert rejected.status_code == 401


def test_challenge_reuse_and_ticket_expiry_and_single_use(client):
    identity = DeviceIdentity.ephemeral()
    headers = _enroll(client, identity)
    assert _approve(client, identity, headers).status_code == 200
    challenge = client.post("/api/v1/agent/challenge", json={"device_id": identity.device_id}).json()
    body = {"device_id": identity.device_id, "challenge_id": challenge["challenge_id"], "signature": _proof(identity, challenge)}
    response = client.post("/api/v1/agent/ticket", json=body)
    assert response.status_code == 200
    assert client.post("/api/v1/agent/ticket", json=body).status_code == 401
    token = response.json()["ticket"]
    with client.app.state.session_factory.begin() as db:
        ticket = db.scalar(select(DeviceTicket).where(DeviceTicket.token_hash == digest(token)))
        ticket.expires_at = now_utc() - timedelta(seconds=1)
    with client.app.state.session_factory.begin() as db:
        assert claim_device_ticket(db, token) is None

    challenge = client.post("/api/v1/agent/challenge", json={"device_id": identity.device_id}).json()
    body = {"device_id": identity.device_id, "challenge_id": challenge["challenge_id"], "signature": _proof(identity, challenge)}
    token = client.post("/api/v1/agent/ticket", json=body).json()["ticket"]
    with client.app.state.session_factory.begin() as db:
        assert str(claim_device_ticket(db, token)) == identity.device_id
    with client.app.state.session_factory.begin() as db:
        assert claim_device_ticket(db, token) is None


def test_expired_and_invalid_enrollment_codes_are_rejected(client):
    identity = DeviceIdentity.ephemeral()
    headers = login(client)
    code = client.post("/api/v1/enrollment-codes", headers={"X-CSRF-Token": headers}).json()["code"]
    with client.app.state.session_factory.begin() as db:
        row = db.scalar(select(EnrollmentCode).where(EnrollmentCode.code_hash == digest(code)))
        row.expires_at = now_utc() - timedelta(seconds=1)
    payload = {"enrollment_code": code, "device_id": identity.device_id,
        "public_key": identity.public_key_pem(), "hostname": "EXPIRED-PC"}
    assert client.post("/api/v1/enrollment/request", json=payload).status_code == 400
    payload["enrollment_code"] = "Z" * 8
    payload["device_id"] = str(uuid4())
    assert client.post("/api/v1/enrollment/request", json=payload).status_code == 400


def test_admin_event_stream_requires_session(client):
    response = client.get("/api/v1/admin/events")
    assert response.status_code == 401


def test_admin_event_hub_delivers_and_unsubscribes():
    import asyncio
    from labguard_server.events import AdminEventHub

    async def exercise():
        hub = AdminEventHub()
        hub.bind(asyncio.get_running_loop())
        stream = hub.subscribe()
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        event = {"type": "device.status", "device_id": str(uuid4()), "agent_state": "ONLINE"}
        hub.publish(event)
        assert await asyncio.wait_for(pending, 1) == event
        await stream.aclose()
        assert not hub.subscribers

    asyncio.run(exercise())
def test_authenticated_admin_event_stream_delivers_status(client):
    import concurrent.futures
    import time

    login(client)
    def receive():
        with client.stream("GET", "/api/v1/admin/events", timeout=3) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.iter_lines()
            return next(lines), next(lines), next(lines)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(receive)
        time.sleep(0.1)
        client.app.state.admin_events.publish({"type": "device.status", "device_id": str(uuid4()),
            "agent_state": "ONLINE", "changed_at": now_utc().isoformat()})
        event, data, separator = pending.result(timeout=3)
    assert event == "event: device.status"
    assert data.startswith("data: {") and '"agent_state":"ONLINE"' in data
    assert separator == ""