"""Exam scheduling, room/device validation, and live health reporting."""
import asyncio
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address, ip_network
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from labguard_server.models import (AuditEvent, Device, DevicePosition, DeviceStatus, Exam,
                                    ExamViolation, Room, ScreenshotCapture, DevicePeripheralEvent,
                                    DeviceWfpEvent, now_utc)
from labguard_server.schemas import ExamCreate


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def exam_out(db: Session, exam: Exam) -> dict:
    room = db.get(Room, exam.room_id)
    count = db.scalar(select(func.count(ExamViolation.id)).where(ExamViolation.exam_id == exam.id)) or 0
    return {"id": exam.id, "room_id": exam.room_id, "room_name": room.name if room else "Unknown room",
            "title": exam.title, "starts_at": exam.starts_at, "ends_at": exam.ends_at,
            "status": exam.status, "device_ids": exam.device_ids, "policy": exam.policy_json,
            "created_at": exam.created_at, "updated_at": exam.updated_at, "violations": count}


def list_exams(db: Session) -> list[dict]:
    return [exam_out(db, exam) for exam in db.scalars(select(Exam).order_by(Exam.starts_at.desc())).all()]


def create_exam(db: Session, admin_id: UUID, body: ExamCreate) -> Exam:
    room = db.get(Room, body.room_id)
    if room is None or room.archived_at is not None:
        raise HTTPException(404, detail={"code": "room_not_found", "message": "Select an active lab room."})
    placed_ids = set(db.scalars(select(DevicePosition.device_id).where(
        DevicePosition.room_id == room.id, DevicePosition.device_id.in_(body.device_ids))).all())
    if placed_ids != set(body.device_ids):
        raise HTTPException(422, detail={"code": "exam_targets_outside_room",
            "message": "Every selected PC must currently be placed in the selected lab."})
    devices = db.scalars(select(Device).where(Device.id.in_(body.device_ids))).all()
    if len(devices) != len(body.device_ids) or any(not d.enabled or d.enrollment_state != "APPROVED" for d in devices):
        raise HTTPException(422, detail={"code": "exam_target_unavailable",
            "message": "Exam targets must be enabled and approved devices."})
    starts, ends = _aware(body.starts_at), _aware(body.ends_at)
    conflicts = db.scalars(select(Exam).where(Exam.status.in_(["SCHEDULED", "ACTIVE"]),
        Exam.starts_at < ends, Exam.ends_at > starts)).all()
    if any(set(item.device_ids).intersection(body.device_ids) for item in conflicts):
        raise HTTPException(409, detail={"code": "exam_device_schedule_conflict",
            "message": "A selected PC is already scheduled for an overlapping exam."})
    row = Exam(id=uuid4(), room_id=room.id, title=body.title, starts_at=starts, ends_at=ends,
        status="SCHEDULED", device_ids=[str(item) for item in body.device_ids],
        policy_json=body.policy.model_dump(mode="json"), created_by=admin_id)
    db.add(row)
    db.add(AuditEvent(actor_type="ADMIN", actor_id=admin_id, action="exam.create", target_type="exam",
        target_id=str(row.id), result="SUCCESS", metadata_json="{}"))
    db.commit()
    db.refresh(row)
    return row


def cancel_exam(db: Session, admin_id: UUID, exam: Exam) -> None:
    if exam.status in {"COMPLETED", "CANCELLED"}:
        return
    exam.status = "CANCELLED"
    exam.updated_at = now_utc()
    db.add(AuditEvent(actor_type="ADMIN", actor_id=admin_id, action="exam.cancel", target_type="exam",
        target_id=str(exam.id), result="SUCCESS", metadata_json="{}"))
    db.commit()


def transition_schedules(db: Session) -> list[tuple[UUID, str]]:
    now = now_utc()
    rows = db.scalars(select(Exam).where(Exam.status.in_(["SCHEDULED", "ACTIVE"]))).all()
    changes = []
    for exam in rows:
        starts, ends = _aware(exam.starts_at), _aware(exam.ends_at)
        state = "COMPLETED" if now >= ends else "ACTIVE" if now >= starts else "SCHEDULED"
        if state != exam.status:
            previous = exam.status
            exam.status, exam.updated_at = state, now
            db.add(AuditEvent(actor_type="SYSTEM", actor_id=None, action=f"exam.{state.lower()}",
                target_type="exam", target_id=str(exam.id), result="SUCCESS",
                metadata_json=f'{{"previous":"{previous}"}}'))
            changes.append((exam.id, state))
    if changes:
        db.commit()
    return changes


def record_health_violations(db: Session) -> list[tuple[UUID, UUID]]:
    """Record one auditable integrity alert per agent offline episode in active exams."""
    now = now_utc()
    exams = db.scalars(select(Exam).where(Exam.status == "ACTIVE")).all()
    added = []
    for exam in exams:
        for device_id_text in exam.device_ids:
            device_id = UUID(device_id_text)
            status = db.get(DeviceStatus, device_id)
            if status and status.agent_state == "ONLINE":
                continue
            heartbeat = _aware(status.last_heartbeat_at).isoformat() if status and status.last_heartbeat_at else "never"
            event_key = f"agent-offline:{device_id}:{heartbeat}"
            exists = db.scalar(select(ExamViolation.id).where(
                ExamViolation.exam_id == exam.id, ExamViolation.event_key == event_key).limit(1))
            if exists:
                continue
            db.add(ExamViolation(exam_id=exam.id, device_id=device_id, event_key=event_key,
                kind="AGENT_OFFLINE", severity="HIGH", details={"agent_state": status.agent_state if status else "NEVER_CONNECTED"},
                occurred_at=now))
            added.append((exam.id, device_id))
    if added:
        db.commit()
    return added


def scan_policy_violations(db: Session) -> tuple[list[tuple[UUID, UUID]], list[dict]]:
    """Match observed WFP and USB events against configured exam policies."""
    now = now_utc()
    created: list[tuple[UUID, UUID]] = []
    captures: list[dict] = []
    exams = db.scalars(select(Exam).where(Exam.status == "ACTIVE")).all()
    for exam in exams:
        policy = exam.policy_json or {}
        devices = [UUID(value) for value in exam.device_ids]
        if not devices:
            continue
        candidates: list[tuple[str, UUID, str, dict, datetime]] = []
        if policy.get("block_usb_storage"):
            rows = db.scalars(select(DevicePeripheralEvent).where(
                DevicePeripheralEvent.device_id.in_(devices),
                DevicePeripheralEvent.occurred_at >= _aware(exam.starts_at),
                DevicePeripheralEvent.occurred_at <= now,
                DevicePeripheralEvent.is_storage.is_(True),
                DevicePeripheralEvent.action == "CONNECTED").order_by(DevicePeripheralEvent.occurred_at).limit(500)).all()
            candidates.extend((f"usb:{row.id}", row.device_id, "USB_STORAGE_CONNECTED",
                {"name": row.name, "category": row.category}, _aware(row.occurred_at)) for row in rows)
        if policy.get("network_mode") == "ALLOW_LIST":
            networks = [ip_network(value, strict=False) for value in policy.get("allowed_networks", [])]
            rows = db.scalars(select(DeviceWfpEvent).where(
                DeviceWfpEvent.device_id.in_(devices),
                DeviceWfpEvent.occurred_at >= _aware(exam.starts_at),
                DeviceWfpEvent.occurred_at <= now,
                DeviceWfpEvent.event_kind == "CONNECTION_ALLOWED").order_by(DeviceWfpEvent.occurred_at).limit(1000)).all()
            for row in rows:
                address = ip_address(row.remote_ip)
                if not any(address.version == network.version and address in network for network in networks):
                    candidates.append((f"wfp:{row.log_generation}:{row.event_record_id}", row.device_id,
                        "NETWORK_OUTSIDE_ALLOW_LIST", {"remote_ip": row.remote_ip, "protocol": row.protocol,
                        "process_path": row.process_path, "event_record_id": row.event_record_id}, _aware(row.occurred_at)))
        for key, device_id, kind, details, occurred_at in candidates:
            if db.scalar(select(ExamViolation.id).where(ExamViolation.exam_id == exam.id,
                    ExamViolation.event_key == key).limit(1)):
                continue
            violation = ExamViolation(exam_id=exam.id, device_id=device_id, event_key=key,
                kind=kind, severity="HIGH", details=details, occurred_at=occurred_at)
            db.add(violation)
            db.flush()
            created.append((exam.id, device_id))
            db.add(AuditEvent(actor_type="SYSTEM", actor_id=None, action="exam.violation",
                target_type="exam_violation", target_id=str(violation.id), result="SUCCESS",
                metadata_json=f'{{"exam_id":"{exam.id}","device_id":"{device_id}","kind":"{kind}"}}'))
            if policy.get("screenshot_on_violation"):
                # Limit automatic evidence to one capture per device per five minutes.
                recent = db.scalar(select(ScreenshotCapture.id).where(
                    ScreenshotCapture.device_id == device_id, ScreenshotCapture.requested_by.is_(None),
                    ScreenshotCapture.created_at >= now - timedelta(minutes=5)).limit(1))
                if recent is None:
                    device = db.get(Device, device_id)
                    if device and device.enabled:
                        capture = ScreenshotCapture(device_id=device_id, requested_by=None,
                            device_name=device.assigned_name or device.hostname, status="PENDING",
                            created_at=now, expires_at=now + timedelta(hours=24))
                        db.add(capture)
                        db.flush()
                        violation.details = {**details, "screenshot_capture_id": str(capture.id)}
                        captures.append({"device_id": device_id,
                            "payload": {"capture_id": str(capture.id),
                                "expires_at": (now + timedelta(seconds=90)).isoformat()}})
                        db.add(AuditEvent(actor_type="SYSTEM", actor_id=None, action="exam.screenshot_requested",
                            target_type="screenshot_capture", target_id=str(capture.id), result="SUCCESS",
                            metadata_json=f'{{"exam_id":"{exam.id}","violation_id":"{violation.id}"}}'))
    if created or captures:
        db.commit()
    return created, captures


async def exam_monitor(application):
    while True:
        try:
            with application.state.session_factory() as db:
                violations = record_health_violations(db)
                policy_violations, captures = scan_policy_violations(db)
                changes = transition_schedules(db)
            for exam_id, status in changes:
                application.state.admin_events.publish({"type": "exam.updated", "exam_id": str(exam_id), "status": status})
            for exam_id, device_id in violations:
                application.state.admin_events.publish({"type": "exam.violation", "exam_id": str(exam_id), "device_id": str(device_id)})
            for exam_id, device_id in policy_violations:
                application.state.admin_events.publish({"type": "exam.violation", "exam_id": str(exam_id), "device_id": str(device_id)})
            from labguard_server.websocket import send_screenshot_request
            for item in captures:
                device_id = item["device_id"]
                sent = await send_screenshot_request(application, device_id, item["payload"])
                if not sent:
                    with application.state.session_factory() as db:
                        capture = db.get(ScreenshotCapture, UUID(item["payload"]["capture_id"]))
                        if capture and capture.status == "PENDING":
                            capture.status, capture.error_code = "FAILED", "agent_unavailable"
                            db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.getLogger("labguard_server.exams").exception("Exam schedule/health monitor failed")
        await asyncio.sleep(5)
