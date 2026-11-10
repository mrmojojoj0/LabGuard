from __future__ import annotations

from datetime import timedelta
from ipaddress import ip_address
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from labguard_server.models import (Device, DeviceCredential, DeviceStatus, DeviceWfpEvent,
                                    DeviceWfpState, now_utc)
from labguard_server.schemas import WfpEventBatchIn

RETENTION_DAYS = 30


def record_wfp_batch(db: Session, device_id: UUID, sequence: int, batch: WfpEventBatchIn):
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (status is None or device is None or credential is None or credential.revoked_at is not None
            or not device.enabled or device.enrollment_state != "APPROVED"):
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return False, "replayed_sequence"

    now = now_utc()
    state = db.scalar(select(DeviceWfpState).where(DeviceWfpState.device_id == device_id).with_for_update())
    generation = str(batch.log_generation)
    if state is not None and state.log_generation == generation and batch.cursor_record_id < state.cursor_record_id:
        status.last_sequence = sequence
        db.commit()
        return False, "cursor_replayed"

    status.last_sequence = sequence
    if state is None:
        state = DeviceWfpState(device_id=device_id, log_generation=generation)
        db.add(state)
    state.log_generation = generation
    state.cursor_record_id = batch.cursor_record_id
    state.status = batch.status
    state.gap_reason = batch.gap_reason
    state.error_code = batch.error_code
    state.updated_at = now

    inserted = 0
    event_ids = [item.event_record_id for item in batch.events]
    existing_ids = set(db.scalars(select(DeviceWfpEvent.event_record_id).where(
        DeviceWfpEvent.device_id == device_id,
        DeviceWfpEvent.log_generation == generation,
        DeviceWfpEvent.event_record_id.in_(event_ids),
    )).all()) if event_ids else set()
    for item in batch.events:
        if item.event_record_id in existing_ids:
            continue
        remote_ip = str(item.source_ip if item.direction == "INCOMING" else item.destination_ip)
        db.add(DeviceWfpEvent(
            device_id=device_id, log_generation=generation, event_record_id=item.event_record_id,
            event_id=item.event_id, occurred_at=item.event_time.astimezone(now.tzinfo),
            event_kind=item.event_kind, direction=item.direction, protocol=item.protocol,
            protocol_number=item.protocol_number, source_ip=str(item.source_ip),
            source_port=item.source_port, destination_ip=str(item.destination_ip),
            destination_port=item.destination_port, remote_ip=remote_ip,
            remote_is_public=ip_address(remote_ip).is_global, process_id=item.process_id,
            process_path=item.process_path,
        ))
        inserted += 1
    db.execute(delete(DeviceWfpEvent).where(
        DeviceWfpEvent.device_id == device_id,
        DeviceWfpEvent.occurred_at < now - timedelta(days=RETENTION_DAYS),
    ))
    db.commit()
    return True, {"inserted": inserted, "status": batch.status}


def wfp_activity(db: Session, *, limit: int = 100, offset: int = 0,
                 device_id: UUID | None = None, event_kind: str | None = None,
                 public_only: bool = False, since_seconds: int | None = None):
    now = now_utc()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    if since_seconds is not None:
        cutoff = max(cutoff, now - timedelta(seconds=since_seconds))
    query = select(DeviceWfpEvent, Device).join(Device, Device.id == DeviceWfpEvent.device_id).where(
        DeviceWfpEvent.occurred_at >= cutoff)
    count_query = select(DeviceWfpEvent.id)
    count_query = count_query.where(DeviceWfpEvent.occurred_at >= cutoff)
    if public_only:
        query = query.where(DeviceWfpEvent.remote_is_public.is_(True))
        count_query = count_query.where(DeviceWfpEvent.remote_is_public.is_(True))
    if device_id is not None:
        query = query.where(DeviceWfpEvent.device_id == device_id)
        count_query = count_query.where(DeviceWfpEvent.device_id == device_id)
    if event_kind is not None:
        query = query.where(DeviceWfpEvent.event_kind == event_kind)
        count_query = count_query.where(DeviceWfpEvent.event_kind == event_kind)
    total = db.scalar(select(func.count()).select_from(count_query.subquery())) or 0
    rows = db.execute(query.order_by(DeviceWfpEvent.occurred_at.desc(), DeviceWfpEvent.id)
                      .offset(offset).limit(limit)).all()
    state_query = select(DeviceWfpState, Device).join(Device, Device.id == DeviceWfpState.device_id)
    if device_id is not None:
        state_query = state_query.where(DeviceWfpState.device_id == device_id)
    states = db.execute(state_query).all()
    return {
        "events": [{
            "id": str(event.id), "device_id": str(device.id),
            "device_name": device.assigned_name or device.hostname,
            "log_generation": event.log_generation, "event_record_id": event.event_record_id,
            "event_id": event.event_id, "event_time": event.occurred_at.isoformat(),
            "event_kind": event.event_kind, "direction": event.direction,
            "protocol": event.protocol, "protocol_number": event.protocol_number,
            "source_ip": event.source_ip, "source_port": event.source_port,
            "destination_ip": event.destination_ip, "destination_port": event.destination_port,
            "remote_ip": event.remote_ip,
            "process_id": event.process_id, "process_path": event.process_path,
            "source": "WFP_EVENT",
        } for event, device in rows],
        "total": total, "limit": limit, "offset": offset,
        "monitoring": [{"device_id": str(device.id), "device_name": device.assigned_name or device.hostname,
            "status": state.status, "gap_reason": state.gap_reason, "error_code": state.error_code,
            "cursor_record_id": state.cursor_record_id, "updated_at": state.updated_at.isoformat(),
            "stale": (now - (state.updated_at.replace(tzinfo=now.tzinfo) if state.updated_at.tzinfo is None
                              else state.updated_at.astimezone(now.tzinfo))).total_seconds() > 90}
            for state, device in states],
    }
