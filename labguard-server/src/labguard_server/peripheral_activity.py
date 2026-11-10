from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from labguard_server.models import (Device, DeviceCredential, DevicePeripheral,
                                    DevicePeripheralEvent, DevicePeripheralSnapshot,
                                    DeviceStatus, now_utc)
from labguard_server.schemas import PeripheralSnapshotIn

RETENTION_DAYS = 90
STALE_AFTER_SECONDS = 90


def record_peripheral_snapshot(db: Session, device_id: UUID, sequence: int,
                               payload: PeripheralSnapshotIn):
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (status is None or device is None or credential is None or credential.revoked_at is not None
            or not device.enabled or device.enrollment_state != "APPROVED"):
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return None, 0, "replayed_sequence"

    now = now_utc()
    status.last_sequence = sequence
    collected_at = payload.collected_at.astimezone(now.tzinfo)
    if collected_at > now + timedelta(minutes=5):
        db.commit()
        return None, 0, "collection_time_in_future"

    current = {row.device_key: row for row in db.scalars(
        select(DevicePeripheral).where(DevicePeripheral.device_id == device_id).with_for_update()).all()}
    reported = {item.device_key: item for item in payload.peripherals}
    changed = 0
    for key, item in reported.items():
        row = current.get(key)
        if row is None:
            row = DevicePeripheral(device_id=device_id, device_key=key, name=item.name,
                                   category=item.category, is_storage=item.is_storage,
                                   connected=True, first_seen_at=now, last_seen_at=now, changed_at=now)
            db.add(row)
            _add_event(db, device_id, item, "CONNECTED", now)
            changed += 1
        else:
            if not row.connected:
                row.connected = True
                row.changed_at = now
                _add_event(db, device_id, item, "CONNECTED", now)
                changed += 1
            row.name = item.name
            row.category = item.category
            row.is_storage = item.is_storage
            row.last_seen_at = now

    for key, row in current.items():
        if row.connected and key not in reported:
            row.connected = False
            row.changed_at = now
            _add_event(db, device_id, row, "DISCONNECTED", now)
            changed += 1

    state = db.get(DevicePeripheralSnapshot, device_id)
    if state is None:
        db.add(DevicePeripheralSnapshot(device_id=device_id, collected_at=collected_at, received_at=now))
    else:
        state.collected_at = collected_at
        state.received_at = now
    db.execute(delete(DevicePeripheralEvent).where(
        DevicePeripheralEvent.device_id == device_id,
        DevicePeripheralEvent.occurred_at < now - timedelta(days=RETENTION_DAYS),
    ))
    db.commit()
    return now, changed, None


def _add_event(db: Session, device_id: UUID, item, action: str, now) -> None:
    db.add(DevicePeripheralEvent(device_id=device_id, device_key=item.device_key,
        name=item.name, category=item.category, is_storage=item.is_storage,
        action=action, occurred_at=now))


def peripheral_activity(db: Session, device_id: UUID, limit: int = 100):
    from labguard_server.models import Device

    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    state = db.get(DevicePeripheralSnapshot, device_id)
    now = now_utc()
    received = state.received_at if state is not None else None
    current = db.scalars(select(DevicePeripheral).where(
        DevicePeripheral.device_id == device_id, DevicePeripheral.connected.is_(True)
    ).order_by(DevicePeripheral.is_storage.desc(), DevicePeripheral.name)).all()
    events = db.scalars(select(DevicePeripheralEvent).where(
        DevicePeripheralEvent.device_id == device_id
    ).order_by(DevicePeripheralEvent.occurred_at.desc()).limit(limit)).all()
    return {
        "device_id": str(device_id),
        "observed_at": received.isoformat() if received else None,
        "stale": received is None or (now - _utc(received)).total_seconds() > STALE_AFTER_SECONDS,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "connected": [_current_out(row) for row in current],
        "events": [_event_out(row) for row in events],
    }


def _current_out(row: DevicePeripheral):
    return {"device_key": row.device_key, "name": row.name, "category": row.category,
            "is_storage": row.is_storage, "first_seen_at": row.first_seen_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat()}


def _event_out(row: DevicePeripheralEvent):
    return {"id": str(row.id), "device_key": row.device_key, "name": row.name,
            "category": row.category, "is_storage": row.is_storage,
            "action": row.action, "occurred_at": row.occurred_at.isoformat()}


def _utc(value):
    from datetime import UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
