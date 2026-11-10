import base64
import hashlib
import os
import asyncio
import getpass
import subprocess
from datetime import timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.models import Device, ScreenshotCapture, now_utc
from labguard_server.services import audit

MAX_IMAGE_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 32 * 1024
CAPTURE_RETENTION = timedelta(hours=24)
REQUEST_TTL = timedelta(minutes=2)
_secured_roots: set[Path] = set()


def expired_at(value) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= now_utc()


def _storage_root(settings) -> Path:
    root = Path(settings.screenshot_storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root not in _secured_roots:
        if os.name == "nt":
            grants = [f"{getpass.getuser()}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]
            result = subprocess.run(["icacls.exe", str(root), "/inheritance:r", "/grant:r", *grants],
                capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                raise RuntimeError("Could not restrict screenshot storage permissions")
        else:
            os.chmod(root, 0o700)
        _secured_roots.add(root)
    return root


def capture_out(row: ScreenshotCapture) -> dict:
    return {"id": str(row.id), "device_id": str(row.device_id), "device_name": row.device_name,
            "status": row.status, "error_code": row.error_code, "image_size_bytes": row.image_size_bytes,
            "created_at": row.created_at.isoformat(), "captured_at": row.captured_at.isoformat() if row.captured_at else None,
            "expires_at": row.expires_at.isoformat(), "sha256": row.image_sha256}


def create_capture(db: Session, device_id: UUID, admin_id: UUID) -> ScreenshotCapture:
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=404, detail={"code": "device_not_found", "message": "Approved device not found"})
    current = db.scalar(select(ScreenshotCapture).where(ScreenshotCapture.device_id == device_id,
        ScreenshotCapture.status == "PENDING").order_by(ScreenshotCapture.created_at.desc()))
    if current is not None:
        if expired_at(current.created_at + REQUEST_TTL):
            current.status, current.error_code = "FAILED", "request_expired"
        else:
            raise HTTPException(status_code=409, detail={"code": "screenshot_pending", "message": "A screenshot request is already pending"})
    row = ScreenshotCapture(id=uuid4(), device_id=device.id, requested_by=admin_id,
        device_name=device.assigned_name or device.hostname, status="PENDING",
        created_at=now_utc(), expires_at=now_utc() + CAPTURE_RETENTION)
    db.add(row)
    audit(db, admin_id, "device.screenshot.requested", "screenshot_capture", str(row.id),
          {"device_id": str(device_id), "retention_hours": 24})
    db.commit()
    db.refresh(row)
    return row


def expire_pending(db: Session, row: ScreenshotCapture) -> ScreenshotCapture:
    if row.status == "PENDING" and expired_at(row.created_at + REQUEST_TTL):
        row.status = "FAILED"
        row.error_code = "request_expired"
        db.commit()
        db.refresh(row)
    return row


def list_captures(db: Session, *, device_id: UUID | None = None, limit: int = 100) -> list[dict]:
    query = select(ScreenshotCapture).where(ScreenshotCapture.expires_at > now_utc())
    if device_id is not None:
        query = query.where(ScreenshotCapture.device_id == device_id)
    return [capture_out(row) for row in db.scalars(query.order_by(ScreenshotCapture.created_at.desc()).limit(limit)).all()]


def receive_chunk(db: Session, settings, device_id: UUID, payload) -> dict:
    row = db.scalar(select(ScreenshotCapture).where(ScreenshotCapture.id == payload.capture_id,
                                                       ScreenshotCapture.device_id == device_id))
    if row is None:
        return {"accepted": False, "reason": "capture_not_found"}
    if row.status == "READY":
        return {"accepted": True, "status": "READY", "duplicate": True}
    if row.status != "PENDING" or expired_at(row.created_at + REQUEST_TTL):
        return {"accepted": False, "reason": "capture_expired"}
    if row.chunk_count is not None and row.chunk_count != payload.chunk_count:
        return {"accepted": False, "reason": "chunk_count_mismatch"}
    try:
        chunk = base64.b64decode(payload.data, validate=True)
    except (ValueError, TypeError):
        return {"accepted": False, "reason": "invalid_chunk"}
    if not chunk or len(chunk) > CHUNK_BYTES:
        return {"accepted": False, "reason": "image_too_large"}
    root = _storage_root(settings)
    partial = root / f"{row.id}.part"
    final = root / f"{row.id}.jpg"
    if partial.parent != root or final.parent != root:
        return {"accepted": False, "reason": "invalid_storage_path"}
    if payload.chunk_index < row.next_chunk_index:
        try:
            with partial.open("rb") as stream:
                stream.seek(payload.chunk_index * CHUNK_BYTES)
                matches = stream.read(len(chunk)) == chunk
        except OSError:
            matches = False
        return ({"accepted": True, "status": row.status, "next_chunk_index": row.next_chunk_index,
                 "duplicate": True} if matches else {"accepted": False, "reason": "chunk_conflict"})
    if payload.chunk_index != row.next_chunk_index:
        return {"accepted": False, "reason": "out_of_order_chunk"}
    if (row.image_size_bytes or 0) + len(chunk) > MAX_IMAGE_BYTES:
        return {"accepted": False, "reason": "image_too_large"}
    with partial.open("r+b" if partial.exists() else "w+b") as stream:
        stream.seek(payload.chunk_index * CHUNK_BYTES)
        stream.write(chunk)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    row.image_size_bytes = (row.image_size_bytes or 0) + len(chunk)
    row.next_chunk_index += 1
    row.chunk_count = payload.chunk_count
    if row.next_chunk_index == row.chunk_count:
        content = partial.read_bytes()
        if len(content) < 4 or not content.startswith(b"\xff\xd8\xff") or not content.endswith(b"\xff\xd9"):
            partial.unlink(missing_ok=True)
            row.status, row.error_code = "FAILED", "invalid_image"
            db.commit()
            return {"accepted": False, "reason": "invalid_image"}
        partial.replace(final)
        row.status = "READY"
        row.image_path = str(final)
        row.image_size_bytes = len(content)
        row.image_sha256 = hashlib.sha256(content).hexdigest()
        row.captured_at = now_utc()
        row.expires_at = row.captured_at + CAPTURE_RETENTION
    db.commit()
    return {"accepted": True, "status": row.status, "next_chunk_index": row.next_chunk_index}


def fail_capture(db: Session, device_id: UUID, capture_id: UUID, error_code: str) -> dict:
    row = db.scalar(select(ScreenshotCapture).where(ScreenshotCapture.id == capture_id,
                                                       ScreenshotCapture.device_id == device_id))
    if row is None:
        return {"accepted": False, "reason": "capture_not_found"}
    if row.status != "PENDING":
        return {"accepted": True, "status": row.status}
    row.status = "FAILED"
    row.error_code = error_code
    db.commit()
    return {"accepted": True, "status": row.status}


def delete_capture(db: Session, settings, row: ScreenshotCapture, admin_id: UUID) -> None:
    root = _storage_root(settings)
    for path in (root / f"{row.id}.part", root / f"{row.id}.jpg"):
        path.unlink(missing_ok=True)
    audit(db, admin_id, "device.screenshot.deleted", "screenshot_capture", str(row.id),
          {"device_id": str(row.device_id), "status": row.status})
    db.delete(row)
    db.commit()


def purge_expired(db: Session, settings) -> int:
    root = _storage_root(settings)
    now = now_utc()
    rows = db.scalars(select(ScreenshotCapture).where(ScreenshotCapture.expires_at <= now)).all()
    for row in rows:
        (root / f"{row.id}.part").unlink(missing_ok=True)
        if row.image_path and Path(row.image_path).resolve().parent == root:
            Path(row.image_path).unlink(missing_ok=True)
        db.delete(row)
    stale_pending = db.scalars(select(ScreenshotCapture).where(
        ScreenshotCapture.status == "PENDING",
        ScreenshotCapture.created_at <= now - REQUEST_TTL)).all()
    for row in stale_pending:
        row.status = "FAILED"
        row.error_code = "request_expired"
    db.commit()
    # Remove abandoned partial files left by interrupted uploads.
    for part in root.glob("*.part"):
        try:
            if now.timestamp() - part.stat().st_mtime > 3600:
                part.unlink(missing_ok=True)
        except OSError:
            continue
    return len(rows) + len(stale_pending)


async def screenshot_retention_monitor(application) -> None:
    while True:
        try:
            def purge():
                with application.state.session_factory() as db:
                    purge_expired(db, application.state.settings)
            await asyncio.to_thread(purge)
        except Exception:
            import logging
            logging.getLogger("labguard_server.screenshots").exception("Screenshot retention cleanup failed")
        await asyncio.sleep(60)
