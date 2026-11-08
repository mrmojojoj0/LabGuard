from __future__ import annotations

import re
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.models import (Device, DeviceCredential, DeviceStatus, RdpAccessRequest,
                                    now_utc)
from labguard_server.schemas import RdpAccessResultIn
from labguard_server.services import audit

_HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST_RE = re.compile(rf"^(?=.{{1,253}}$){_HOST_LABEL}(?:\.{_HOST_LABEL})*\.?$")
REQUEST_TTL = timedelta(minutes=2)
ACCESS_TTL = timedelta(minutes=60)


def hostname_is_safe(hostname: str) -> bool:
    return bool(_HOST_RE.fullmatch(hostname))


def create_rdp_access_request(db: Session, device_id: UUID, administrator_id: UUID) -> RdpAccessRequest:
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=409, detail={"code": "device_unavailable", "message": "This device is not enabled and approved"})
    if not hostname_is_safe(device.hostname):
        raise HTTPException(status_code=409, detail={"code": "rdp_hostname_unavailable", "message": "The device has no safe Windows host name for an RDP connection"})
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    status = db.get(DeviceStatus, device_id)
    if credential is None or credential.revoked_at is not None or status is None or status.agent_state not in {"ONLINE", "DELAYED"}:
        raise HTTPException(status_code=409, detail={"code": "device_offline", "message": "The device must be online with an active credential to prepare RDP"})
    now = now_utc()
    db.query(RdpAccessRequest).filter(
        RdpAccessRequest.device_id == device_id,
        RdpAccessRequest.status == "PENDING",
        RdpAccessRequest.expires_at <= now,
    ).update({"status": "EXPIRED"}, synchronize_session=False)
    pending = db.scalar(select(RdpAccessRequest.id).where(
        RdpAccessRequest.device_id == device_id,
        RdpAccessRequest.status == "PENDING",
        RdpAccessRequest.expires_at > now,
    ).with_for_update().limit(1))
    if pending is not None:
        raise HTTPException(status_code=409, detail={"code": "rdp_request_pending", "message": "An RDP request is already being prepared for this device"})
    request = RdpAccessRequest(device_id=device_id, requested_by=administrator_id,
        hostname=device.hostname, status="PENDING", created_at=now,
        expires_at=now + REQUEST_TTL, access_expires_at=now + ACCESS_TTL)
    db.add(request)
    db.flush()
    audit(db, administrator_id, "rdp.access.requested", "rdp_access_request", str(request.id), {
        "device_id": str(device_id), "hostname": device.hostname,
        "access_expires_at": request.access_expires_at.isoformat(),
    })
    db.commit()
    db.refresh(request)
    return request


def expire_rdp_request(db: Session, request: RdpAccessRequest) -> RdpAccessRequest:
    if request.status == "PENDING" and request.expires_at.replace(tzinfo=now_utc().tzinfo) <= now_utc():
        request.status = "EXPIRED"
        db.commit()
        db.refresh(request)
    return request


def record_rdp_access_result(db: Session, device_id: UUID, sequence: int,
                             payload: RdpAccessResultIn) -> dict:
    status = db.scalar(select(DeviceStatus).where(
        DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (status is None or device is None or credential is None or credential.revoked_at is not None
            or not device.enabled or device.enrollment_state != "APPROVED"):
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return {"accepted": False, "reason": "replayed_sequence"}
    status.last_sequence = sequence
    request = db.scalar(select(RdpAccessRequest).where(
        RdpAccessRequest.id == payload.request_id,
        RdpAccessRequest.device_id == device_id,
    ).with_for_update())
    now = now_utc()
    if request is None:
        db.commit()
        return {"accepted": False, "reason": "rdp_request_not_found"}
    if request.status != "PENDING" or request.expires_at.replace(tzinfo=now.tzinfo) <= now:
        if request.status == "PENDING":
            request.status = "EXPIRED"
        db.commit()
        return {"accepted": False, "reason": "rdp_request_expired"}
    request.status = payload.status
    request.error_code = payload.error_code if payload.status == "FAILED" else None
    request.rdp_username = payload.username if payload.status == "READY" else None
    audit(db, None, "rdp.access.prepared" if payload.status == "READY" else "rdp.access.failed",
          "rdp_access_request", str(request.id), {"device_id": str(device_id),
          "status": request.status, "error_code": request.error_code}, actor_type="DEVICE")
    db.commit()
    return {"accepted": True, "status": request.status, "request_id": str(request.id)}


def rdp_request_out(request: RdpAccessRequest) -> dict:
    return {"id": str(request.id), "device_id": str(request.device_id),
            "hostname": request.hostname, "username": request.rdp_username, "status": request.status,
            "error_code": request.error_code, "created_at": request.created_at.isoformat(),
            "expires_at": request.expires_at.isoformat(),
            "access_expires_at": request.access_expires_at.isoformat()}
