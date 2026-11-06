import json
from datetime import timedelta
from datetime import UTC, datetime
from uuid import UUID, uuid4
import base64
import hashlib
import secrets

from fastapi import HTTPException
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from labguard_server.config import Settings
from labguard_server.models import (AdminSession, Administrator, AuditEvent, Device, DeviceAuthChallenge,
                                    DeviceCredential, DevicePosition, DeviceStatus, DeviceStatusEvent, DeviceTicket,
                                    EnrollmentCode, Room, now_utc)
from labguard_server.schemas import RoomLayout
from labguard_server.security import create_admin_session, digest, hash_password, verify_password


def audit(db: Session, actor_id: UUID | None, action: str, target_type: str, target_id: str | None, metadata=None, actor_type="ADMIN"):
    db.add(AuditEvent(actor_type=actor_type, actor_id=actor_id, action=action, target_type=target_type,
                      target_id=target_id, result="SUCCESS", metadata_json=json.dumps(metadata or {}, separators=(",", ":"))))


def delete_device(db: Session, actor_id: UUID, device: Device) -> None:
    """Revoke credentials, preserve an audit snapshot, and cascade owned device data."""
    device_id = str(device.id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device.id).with_for_update())
    if credential is not None:
        credential.revoked_at = credential.revoked_at or now_utc()
        db.flush()
    audit(db, actor_id, "device.delete", "device", device_id, {
        "assigned_name": device.assigned_name,
        "hostname": device.hostname,
        "enrollment_state": device.enrollment_state,
    })
    db.delete(device)
    db.commit()


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def normalized_ed25519_key(pem: str) -> tuple[str, str]:
    try:
        key = serialization.load_pem_public_key(pem.encode("ascii"))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_device_key", "message": "A valid Ed25519 PEM public key is required"}) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_key", "message": "Only Ed25519 public keys are accepted"})
    canonical = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    fingerprint = hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    return canonical, fingerprint


def authenticate(db: Session, username: str, password: str, settings: Settings):
    normalized = username.strip().casefold()
    admin = db.scalar(select(Administrator).where(Administrator.username == normalized))
    if admin is None or not admin.enabled or not verify_password(admin.password_hash, password):
        audit(db, admin.id if admin else None, "auth.login_failed", "administrator", str(admin.id) if admin else None)
        db.commit()
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "Invalid username or password"})
    admin.last_login_at = now_utc()
    raw, csrf, session = create_admin_session(db, admin, settings)
    audit(db, admin.id, "auth.login", "administrator", str(admin.id))
    db.commit()
    return admin, raw, csrf, session


_ENROLLMENT_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def create_enrollment_code(db: Session, admin_id: UUID, settings: Settings):
    # Eight symbols from a 32-character alphabet provide 40 random bits; avoid lookalike characters.
    raw = "".join(secrets.choice(_ENROLLMENT_CODE_ALPHABET) for _ in range(8))
    row = EnrollmentCode(code_hash=digest(raw), created_by=admin_id,
                         expires_at=now_utc() + timedelta(minutes=settings.enrollment_code_ttl_minutes))
    db.add(row)
    audit(db, admin_id, "enrollment_code.create", "enrollment_code", str(row.id))
    db.commit()
    return row, raw


def submit_enrollment(db: Session, code: str, device_id: UUID, public_key: str, hostname: str, agent_version: str | None):
    public_key, _fingerprint = normalized_ed25519_key(public_key)
    record = db.scalar(select(EnrollmentCode).where(EnrollmentCode.code_hash == digest(code)).with_for_update())
    now = now_utc()
    if record is None or record.consumed_at or record.revoked_at or record.expires_at.replace(tzinfo=now.tzinfo) <= now:
        raise HTTPException(status_code=400, detail={"code": "invalid_enrollment_code", "message": "Enrollment code is invalid or expired"})
    if db.get(Device, device_id) is not None:
        raise HTTPException(status_code=409, detail={"code": "device_exists", "message": "Device UUID is already registered"})
    record.consumed_at = now
    device = Device(id=device_id, public_key=public_key, hostname=hostname.strip(), agent_version=agent_version,
                    enrollment_state="PENDING", enabled=True)
    db.add(device)
    audit(db, device_id, "device.enrollment_requested", "device", str(device_id), actor_type="DEVICE")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "device_exists", "message": "Device UUID is already registered"}) from exc
    return device


def approve_device(db: Session, admin_id: UUID, device: Device, assigned_name: str):
    if device.enrollment_state != "PENDING":
        raise HTTPException(status_code=409, detail={"code": "invalid_device_state", "message": "Only pending devices can be approved"})
    device.assigned_name = assigned_name.strip()
    device.enrollment_state = "APPROVED"
    device.approved_at = now_utc()
    _key, fingerprint = normalized_ed25519_key(device.public_key)
    db.add(DeviceCredential(device_id=device.id, public_key=device.public_key, fingerprint=fingerprint))
    db.add(DeviceStatus(device_id=device.id, agent_state="NEVER_CONNECTED", network_state="UNKNOWN", last_sequence=0))
    db.add(DeviceStatusEvent(device_id=device.id, previous_state="UNREGISTERED", new_state="NEVER_CONNECTED",
                             reason="device_approved", occurred_at=now_utc()))
    audit(db, admin_id, "device.approve", "device", str(device.id), {"assigned_name": device.assigned_name, "credential_fingerprint": fingerprint})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "name_conflict", "message": "Assigned device name already exists"}) from exc
    return device


def create_device_challenge(db: Session, device_id: UUID, ttl_seconds: int):
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    device = db.get(Device, device_id)
    if credential is None or credential.revoked_at is not None or device is None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=401, detail={"code": "device_not_authenticated", "message": "Device is not approved or its credential is revoked"})
    nonce = secrets.token_urlsafe(32)
    challenge = DeviceAuthChallenge(device_id=device_id, nonce_hash=digest(nonce), expires_at=now_utc() + timedelta(seconds=ttl_seconds))
    db.add(challenge)
    db.commit()
    return challenge, nonce


def issue_device_ticket(db: Session, challenge_id: UUID, device_id: UUID, signature: str, ttl_seconds: int):
    challenge = db.scalar(select(DeviceAuthChallenge).where(DeviceAuthChallenge.id == challenge_id).with_for_update())
    now = now_utc()
    if challenge is None or challenge.device_id != device_id or challenge.consumed_at is not None or aware(challenge.expires_at) <= now:
        raise HTTPException(status_code=401, detail={"code": "invalid_challenge", "message": "Challenge is invalid, expired, or already used"})
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    device = db.get(Device, device_id)
    if credential is None or credential.revoked_at is not None or device is None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=401, detail={"code": "device_not_authenticated", "message": "Device credential is unavailable"})
    try:
        sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        public_key = serialization.load_pem_public_key(credential.public_key.encode("ascii"))
        message = f"labguard.device.auth.v1\n{device_id}\n{challenge.id}\n{challenge.nonce_hash}".encode("ascii")
        # nonce_hash is what the server issued and is part of the signed proof.
        public_key.verify(sig, message)
    except (ValueError, TypeError, UnicodeError, InvalidSignature) as exc:
        challenge.consumed_at = now
        db.commit()
        raise HTTPException(status_code=401, detail={"code": "invalid_device_proof", "message": "Device signature verification failed"}) from exc
    challenge.consumed_at = now
    token = secrets.token_urlsafe(32)
    db.add(DeviceTicket(token_hash=digest(token), device_id=device_id, expires_at=now + timedelta(seconds=ttl_seconds)))
    db.commit()
    return token


def claim_device_ticket(db: Session, token: str):
    ticket = db.scalar(select(DeviceTicket).where(DeviceTicket.token_hash == digest(token)).with_for_update())
    now = now_utc()
    if ticket is None or ticket.consumed_at is not None or aware(ticket.expires_at) <= now:
        return None
    device = db.get(Device, ticket.device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == ticket.device_id))
    if device is None or credential is None or credential.revoked_at is not None or not device.enabled or device.enrollment_state != "APPROVED":
        ticket.consumed_at = now
        db.commit()
        return None
    ticket.consumed_at = now
    db.commit()
    return device.id


def record_agent_event(db: Session, device_id: UUID, sequence: int, event_type: str, agent_version: str | None = None):
    status_row = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if status_row is None or device is None or credential is None or credential.revoked_at is not None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status_row.last_sequence:
        raise HTTPException(status_code=409, detail={"code": "replayed_sequence", "message": "Event sequence must increase monotonically"})
    now = now_utc()
    previous = status_row.agent_state
    status_row.last_sequence = sequence
    status_row.last_heartbeat_at = now
    device.last_seen_at = now
    if agent_version:
        device.agent_version = agent_version[:50]
    status_row.agent_state = "ONLINE"
    if previous != "ONLINE":
        status_row.changed_at = now
        db.add(DeviceStatusEvent(device_id=device_id, previous_state=previous, new_state="ONLINE", reason=event_type, occurred_at=now))
    db.commit()
    return now


def refresh_device_states(db: Session, delayed_after: float, offline_after: float, on_change=None):
    now = now_utc()
    statuses = db.scalars(select(DeviceStatus)).all()
    changed = 0
    for status_row in statuses:
        device = db.get(Device, status_row.device_id)
        if device is None:
            continue
        credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == status_row.device_id))
        if credential is None or credential.revoked_at is not None:
            desired = "QUARANTINED"
        elif not device.enabled:
            desired = "DISABLED"
        elif status_row.last_heartbeat_at is None:
            desired = "NEVER_CONNECTED"
        else:
            age = (now - aware(status_row.last_heartbeat_at)).total_seconds()
            desired = "OFFLINE" if age >= offline_after else "DELAYED" if age >= delayed_after else "ONLINE"
        if desired != status_row.agent_state:
            previous = status_row.agent_state
            status_row.agent_state = desired
            status_row.changed_at = now
            db.add(DeviceStatusEvent(device_id=status_row.device_id, previous_state=previous, new_state=desired,
                                     reason="heartbeat_timeout" if desired in {"DELAYED", "OFFLINE"} else "administrative_state", occurred_at=now))
            if on_change is not None:
                on_change(status_row.device_id, previous, desired, now)
            changed += 1
    if changed:
        db.commit()
    return changed


def create_room(db: Session, admin_id: UUID, values):
    room = Room(**values)
    db.add(room)
    audit(db, admin_id, "room.create", "room", str(room.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "room_name_conflict", "message": "Room name already exists"}) from exc
    db.refresh(room)
    return room


def update_room(db: Session, admin_id: UUID, room: Room, changes: dict):
    if "grid_rows" in changes or "grid_columns" in changes:
        new_rows = changes.get("grid_rows", room.grid_rows)
        new_columns = changes.get("grid_columns", room.grid_columns)
        positions = db.scalars(select(DevicePosition).where(DevicePosition.room_id == room.id)).all()
        if any(pos.row_index >= new_rows or pos.column_index >= new_columns for pos in positions):
            raise HTTPException(status_code=409, detail={"code": "layout_out_of_bounds", "message": "Resize would invalidate existing device positions"})
    for key, value in changes.items():
        setattr(room, key, value)
    audit(db, admin_id, "room.update", "room", str(room.id), changes)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "room_name_conflict", "message": "Room name already exists"}) from exc
    db.refresh(room)
    return room


def save_layout(db: Session, admin_id: UUID, room: Room, layout: RoomLayout):
    for item in layout.assignments:
        if item.row >= layout.rows or item.column >= layout.columns:
            raise HTTPException(status_code=422, detail={"code": "cell_out_of_bounds", "message": "Assignment is outside the new grid dimensions"})
        device = db.get(Device, item.device_id)
        if device is None or device.enrollment_state != "APPROVED" or not device.enabled:
            raise HTTPException(status_code=422, detail={"code": "device_unavailable", "message": "Only approved enabled devices may be positioned"})
    room.grid_rows, room.grid_columns = layout.rows, layout.columns
    # A device may move between rooms; replacement is performed as one transaction.
    ids = [item.device_id for item in layout.assignments]
    for old in db.scalars(select(DevicePosition).where(DevicePosition.room_id == room.id)).all():
        db.delete(old)
    if ids:
        for old in db.scalars(select(DevicePosition).where(DevicePosition.device_id.in_(ids))).all():
            db.delete(old)
    db.flush()
    for item in layout.assignments:
        db.add(DevicePosition(device_id=item.device_id, room_id=room.id, row_index=item.row, column_index=item.column))
    audit(db, admin_id, "room.layout_update", "room", str(room.id), {"assignments": len(ids)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "grid_conflict", "message": "Grid position conflicts with an existing assignment"}) from exc
    db.refresh(room)
    return room
