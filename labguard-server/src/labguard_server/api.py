from uuid import UUID
from time import monotonic
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.db import get_db
from labguard_server.models import AuditEvent, Device, DeviceAuthChallenge, DeviceCredential, DevicePosition, DeviceStatus, DeviceStatusEvent, Room, now_utc
from labguard_server.schemas import (DeviceApproval, DeviceChallengeRequest, DeviceOut, DeviceTicketRequest, EnrollmentCodeOut, EnrollmentRequestIn,
                                     LayoutOut, LoginRequest, RoomCreate, RoomLayout, RoomOut, RoomPatch)
from labguard_server.security import csrf_protected, digest, require_role
from labguard_server.services import (approve_device, audit, authenticate, create_enrollment_code, create_room,
                                      create_device_challenge, issue_device_ticket, save_layout, submit_enrollment,
                                      update_room)

router = APIRouter(prefix="/api/v1")
_login_failures: dict[str, list[float]] = {}
_enrollment_attempts: dict[str, list[float]] = {}
_device_auth_attempts: dict[str, list[float]] = {}


@router.post("/auth/login")
def login(body: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    key = (request.client.host if request.client else "unknown")
    now = monotonic()
    recent = [stamp for stamp in _login_failures.get(key, []) if now - stamp < 300]
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail={"code": "login_rate_limited", "message": "Too many login attempts"}, headers={"Retry-After": "300"})
    try:
        admin, token, csrf, session = authenticate(db, body.username, body.password, request.app.state.settings)
    except HTTPException:
        recent.append(now)
        _login_failures[key] = recent
        raise
    _login_failures.pop(key, None)
    response.set_cookie("labguard_session", token, httponly=True, secure=request.app.state.settings.cookie_secure,
                        samesite="strict", max_age=int(request.app.state.settings.session_ttl_hours * 3600), path="/")
    return {"administrator": {"id": str(admin.id), "username": admin.username, "role": admin.role}, "csrf_token": csrf,
            "expires_at": session.expires_at.isoformat()}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, auth=Depends(csrf_protected), db: Session = Depends(get_db)):
    _admin, session_row = auth
    session_row.revoked_at = now_utc()
    audit(db, _admin.id, "auth.logout", "administrator", str(_admin.id))
    db.commit()
    response.delete_cookie("labguard_session", path="/", httponly=True, secure=request.app.state.settings.cookie_secure,
                           samesite="strict")
    response.status_code = 204
    return response


@router.get("/auth/me")
def me(admin=Depends(require_role("VIEWER"))):
    return {"id": str(admin.id), "username": admin.username, "role": admin.role}


@router.post("/enrollment-codes", response_model=EnrollmentCodeOut)
def make_enrollment_code(request: Request, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    row, raw = create_enrollment_code(db, admin.id, request.app.state.settings)
    return EnrollmentCodeOut(id=row.id, code=raw, expires_at=row.expires_at)


@router.post("/enrollment/request", response_model=DeviceOut, status_code=201)
def enrollment_request(request: Request, body: EnrollmentRequestIn, db: Session = Depends(get_db)):
    # Bound unauthenticated code-guess attempts per source address in this single-instance MVP.
    key = request.client.host if request.client else "unknown"
    now = monotonic()
    recent = [stamp for stamp in _enrollment_attempts.get(key, []) if now - stamp < 300]
    if len(recent) >= 20:
        raise HTTPException(status_code=429, detail={"code": "enrollment_rate_limited", "message": "Too many enrollment attempts"}, headers={"Retry-After": "300"})
    recent.append(now)
    _enrollment_attempts[key] = recent
    return submit_enrollment(db, body.enrollment_code, body.device_id, body.public_key, body.hostname, body.agent_version)


@router.get("/enrollment/requests", response_model=list[DeviceOut])
def pending_enrollments(_admin=Depends(require_role("LAB_ADMIN")), db: Session = Depends(get_db)):
    return db.scalars(select(Device).where(Device.enrollment_state == "PENDING").order_by(Device.created_at)).all()


@router.post("/enrollment/requests/{device_id}/approve", response_model=DeviceOut)
def approve_enrollment(device_id: UUID, body: DeviceApproval, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    return approve_device(db, admin.id, device, body.assigned_name)


@router.post("/enrollment/requests/{device_id}/reject", response_model=DeviceOut)
def reject_enrollment(device_id: UUID, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    if device.enrollment_state != "PENDING":
        raise HTTPException(status_code=409, detail={"code": "invalid_device_state", "message": "Only pending devices can be rejected"})
    device.enrollment_state = "REJECTED"
    audit(db, admin.id, "device.reject", "device", str(device.id))
    db.commit()
    return device


@router.post("/devices/{device_id}/credential/revoke")
async def revoke_device_credential(device_id: UUID, request: Request, admin=Depends(require_role("SUPER_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if credential is None:
        raise HTTPException(status_code=404, detail={"code": "credential_not_found", "message": "Device credential not found"})
    if credential.revoked_at is None:
        credential.revoked_at = now_utc()
        status_row = db.get(DeviceStatus, device_id)
        if status_row is not None and status_row.agent_state != "QUARANTINED":
            previous = status_row.agent_state
            status_row.agent_state = "QUARANTINED"
            status_row.changed_at = now_utc()
            db.add(DeviceStatusEvent(device_id=device_id, previous_state=previous, new_state="QUARANTINED",
                                     reason="credential_revoked", occurred_at=status_row.changed_at))
        audit(db, admin.id, "device.credential_revoke", "device", str(device_id), {"fingerprint": credential.fingerprint})
        db.commit()
        request.app.state.admin_events.publish({"type": "device.status", "device_id": str(device_id),
            "agent_state": "QUARANTINED", "changed_at": status_row.changed_at.isoformat() if status_row else now_utc().isoformat()})
        active = request.app.state.active_devices.get(device_id)
        if active is not None:
            await active.close(code=4401, reason="credential_revoked")
    return {"device_id": str(device_id), "revoked": True}


@router.get("/admin/events")
async def administrator_events(request: Request, _admin=Depends(require_role("VIEWER"))):
    hub = request.app.state.admin_events

    async def stream():
        async for event in hub.subscribe():
            if event is None:
                yield ": keep-alive\n\n"
                continue
            yield f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/devices/{device_id}/status")
def device_status(device_id: UUID, request: Request, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    status_row = db.get(DeviceStatus, device_id)
    device = db.get(Device, device_id)
    if status_row is None or device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device status not found"})
    return {"device_id": str(device_id), "agent_state": status_row.agent_state, "network_state": status_row.network_state,
            "last_heartbeat_at": status_row.last_heartbeat_at.isoformat() if status_row.last_heartbeat_at else None,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "changed_at": status_row.changed_at.isoformat(),
            "connected": device_id in request.app.state.active_devices}


@router.get("/rooms/{room_id}/layout", response_model=LayoutOut)
def get_room_layout(room_id: UUID, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if room is None or room.archived_at is not None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Room not found"})
    positions = db.scalars(select(DevicePosition).where(DevicePosition.room_id == room.id)
                           .order_by(DevicePosition.row_index, DevicePosition.column_index)).all()
    return LayoutOut(room=room, assignments=[{"device_id": p.device_id, "row": p.row_index, "column": p.column_index}
                                             for p in positions])


@router.post("/agent/challenge")
def agent_challenge(body: DeviceChallengeRequest, request: Request, db: Session = Depends(get_db)):
    device_id = body.device_id
    key = request.client.host if request.client else "unknown"
    recent = [stamp for stamp in _device_auth_attempts.get(key, []) if monotonic() - stamp < 300]
    if len(recent) >= 30:
        raise HTTPException(status_code=429, detail={"code": "device_auth_rate_limited", "message": "Too many device authentication attempts"}, headers={"Retry-After": "300"})
    recent.append(monotonic())
    _device_auth_attempts[key] = recent
    challenge, nonce = create_device_challenge(db, device_id, request.app.state.settings.device_challenge_ttl_seconds)
    return {"challenge_id": str(challenge.id), "nonce": nonce, "expires_at": challenge.expires_at.isoformat()}


@router.post("/agent/ticket")
def agent_ticket(body: DeviceTicketRequest, request: Request, db: Session = Depends(get_db)):
    token = issue_device_ticket(db, body.challenge_id, body.device_id, body.signature, request.app.state.settings.device_ticket_ttl_seconds)
    return {"ticket": token, "expires_in_seconds": request.app.state.settings.device_ticket_ttl_seconds}


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(_admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    return db.scalars(select(Device).order_by(Device.created_at)).all()


@router.post("/rooms", response_model=RoomOut, status_code=201)
def add_room(body: RoomCreate, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    return create_room(db, admin.id, body.model_dump())


@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(_admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    return db.scalars(select(Room).where(Room.archived_at.is_(None)).order_by(Room.name)).all()


@router.get("/rooms/{room_id}", response_model=RoomOut)
def get_room(room_id: UUID, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if room is None or room.archived_at is not None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Room not found"})
    return room


@router.patch("/rooms/{room_id}", response_model=RoomOut)
def patch_room(room_id: UUID, body: RoomPatch, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if room is None or room.archived_at is not None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Room not found"})
    return update_room(db, admin.id, room, body.model_dump(exclude_unset=True))


@router.delete("/rooms/{room_id}", status_code=204)
def delete_room(room_id: UUID, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if room is None or room.archived_at is not None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Room not found"})
    if db.scalar(select(DevicePosition.device_id).where(DevicePosition.room_id == room_id).limit(1)):
        room.archived_at = now_utc()
        audit(db, admin.id, "room.archive", "room", str(room.id))
    else:
        audit(db, admin.id, "room.delete", "room", str(room.id))
        db.delete(room)
    db.commit()
    return Response(status_code=204)


@router.put("/rooms/{room_id}/layout", response_model=LayoutOut)
def put_layout(room_id: UUID, body: RoomLayout, admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if room is None or room.archived_at is not None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Room not found"})
    room = save_layout(db, admin.id, room, body)
    positions = db.scalars(select(DevicePosition).where(DevicePosition.room_id == room.id).order_by(DevicePosition.row_index, DevicePosition.column_index)).all()
    return LayoutOut(room=room, assignments=[{"device_id": p.device_id, "row": p.row_index, "column": p.column_index} for p in positions])


@router.get("/audit-events")
def list_audit_events(_admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db), limit: int = 50):
    limit = min(max(limit, 1), 200)
    records = db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit)).all()
    return [{"id": str(x.id), "actor_type": x.actor_type, "actor_id": str(x.actor_id) if x.actor_id else None,
             "action": x.action, "target_type": x.target_type, "target_id": x.target_id, "result": x.result,
             "occurred_at": x.occurred_at.isoformat(), "metadata": json.loads(x.metadata_json or "{}")} for x in records]
