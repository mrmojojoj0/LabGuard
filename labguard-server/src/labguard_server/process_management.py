"""Persistent, authorized process inspection and identity-bound actions."""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.models import (Device, DeviceCredential, DeviceProcessRequest, DeviceStatus,
                                    now_utc)
from labguard_server.schemas import ProcessRequestCreate, ProcessResultIn
from labguard_server.services import audit, aware

REQUEST_TTL = timedelta(seconds=90)
MAX_PROCESS_RESULTS = 1000


def create_process_request(db: Session, device_id: UUID, administrator_id: UUID,
                           body: ProcessRequestCreate) -> DeviceProcessRequest:
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update())
    status = db.get(DeviceStatus, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (device is None or not device.enabled or device.enrollment_state != "APPROVED"
            or status is None or status.agent_state not in {"ONLINE", "DELAYED"}
            or credential is None or credential.revoked_at is not None):
        raise HTTPException(status_code=409, detail={"code": "device_offline", "message": "The device must be online and authorized"})

    now = now_utc()
    db.query(DeviceProcessRequest).filter(
        DeviceProcessRequest.device_id == device_id,
        DeviceProcessRequest.status == "PENDING",
        DeviceProcessRequest.expires_at <= now,
    ).update({"status": "EXPIRED"}, synchronize_session=False)
    pending = db.scalar(select(DeviceProcessRequest.id).where(
        DeviceProcessRequest.device_id == device_id,
        DeviceProcessRequest.status == "PENDING",
        DeviceProcessRequest.expires_at > now,
    ).with_for_update().limit(1))
    if pending is not None:
        raise HTTPException(status_code=409, detail={"code": "process_request_pending", "message": "A process operation is already pending for this device"})

    request = DeviceProcessRequest(
        device_id=device_id, requested_by=administrator_id, operation=body.operation,
        status="PENDING", target_pid=body.target_pid,
        target_created_at_us=body.target_created_at_us,
        created_at=now, expires_at=now + REQUEST_TTL,
    )
    db.add(request)
    db.flush()
    audit(db, administrator_id, "device.process.requested", "device_process_request", str(request.id), {
        "device_id": str(device_id), "operation": body.operation,
        "target_pid": body.target_pid, "target_created_at_us": body.target_created_at_us,
    })
    db.commit()
    db.refresh(request)
    return request


def expire_process_request(db: Session, request: DeviceProcessRequest) -> DeviceProcessRequest:
    if request.status == "PENDING" and aware(request.expires_at) <= now_utc():
        request.status = "EXPIRED"
        request.result_code = "request_expired"
        request.completed_at = now_utc()
        db.commit()
        db.refresh(request)
    return request


def record_process_result(db: Session, device_id: UUID, sequence: int,
                          payload: ProcessResultIn) -> dict:
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (status is None or device is None or credential is None or credential.revoked_at is not None
            or not device.enabled or device.enrollment_state != "APPROVED"):
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return {"accepted": False, "reason": "replayed_sequence"}
    status.last_sequence = sequence
    request = db.scalar(select(DeviceProcessRequest).where(
        DeviceProcessRequest.id == payload.request_id,
        DeviceProcessRequest.device_id == device_id,
    ).with_for_update())
    now = now_utc()
    if request is None:
        db.commit()
        return {"accepted": False, "reason": "process_request_not_found"}
    if request.status != "PENDING" or aware(request.expires_at) <= now:
        if request.status == "PENDING":
            request.status, request.result_code, request.completed_at = "EXPIRED", "request_expired", now
        db.commit()
        return {"accepted": False, "reason": "process_request_expired"}

    if request.operation == "LIST":
        if payload.result_code not in (None, "request_expired", "process_list_failed", "process_list_truncated"):
            db.commit()
            return {"accepted": False, "reason": "invalid_process_list_result"}
        if request.batch_count is not None and request.batch_count != payload.batch_count:
            db.commit()
            return {"accepted": False, "reason": "process_batch_count_mismatch"}
        request.batch_count = payload.batch_count
        batches = dict(request.received_batches or {})
        if batches and request.result_code != payload.result_code:
            db.commit()
            return {"accepted": False, "reason": "process_batch_result_mismatch"}
        if not batches:
            request.result_code = payload.result_code
        batch_key = str(payload.batch_index)
        batch_value = [item.model_dump(mode="json") for item in payload.processes]
        if batch_key in batches and batches[batch_key] != batch_value:
            db.commit()
            return {"accepted": False, "reason": "process_batch_conflict"}
        batches[batch_key] = batch_value
        request.received_batches = batches
        if payload.result_code == "request_expired":
            request.status, request.result_code, request.completed_at = "EXPIRED", payload.result_code, now
        elif payload.result_code == "process_list_failed":
            request.status, request.result_code, request.completed_at = "FAILED", payload.result_code, now
        elif len(batches) == payload.batch_count:
            items = [entry for index in range(payload.batch_count)
                     for entry in batches.get(str(index), [])]
            if len(items) > MAX_PROCESS_RESULTS or len({item["pid"] for item in items}) != len(items):
                request.status, request.result_code = "FAILED", "invalid_process_list"
            else:
                request.status, request.result_code, request.process_items = "COMPLETE", payload.result_code, items
            request.completed_at = now
    else:
        expected_codes = {
            "TERMINATE": {"terminated", "process_not_found", "pid_reused", "access_denied",
                          "invalid_process_identity", "protected_process", "terminate_timeout", "operation_failed", "request_expired"},
            "KILL": {"killed", "process_not_found", "pid_reused", "access_denied",
                     "invalid_process_identity", "protected_process", "kill_timeout", "operation_failed", "request_expired"},
        }
        if (payload.batch_count != 1 or payload.batch_index != 0 or payload.processes
                or payload.result_code not in expected_codes[request.operation]):
            db.commit()
            return {"accepted": False, "reason": "invalid_process_action_result"}
        request.status = "EXPIRED" if payload.result_code == "request_expired" else "COMPLETE"
        request.result_code, request.completed_at = payload.result_code, now

    if request.status in {"COMPLETE", "FAILED"}:
        audit(db, None, "device.process.completed", "device_process_request", str(request.id), {
            "device_id": str(device_id), "operation": request.operation,
            "status": request.status, "result_code": request.result_code,
        }, actor_type="DEVICE")
    db.commit()
    return {"accepted": True, "status": request.status}


def process_request_out(request: DeviceProcessRequest) -> dict:
    items = request.process_items if request.status == "COMPLETE" and request.operation == "LIST" else None
    return {
        "id": str(request.id), "device_id": str(request.device_id),
        "operation": request.operation, "status": request.status,
        "target_pid": request.target_pid, "target_created_at_us": request.target_created_at_us,
        "result_code": request.result_code, "processes": items,
        "created_at": request.created_at.isoformat(), "expires_at": request.expires_at.isoformat(),
        "completed_at": request.completed_at.isoformat() if request.completed_at else None,
    }
