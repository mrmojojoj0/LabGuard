from uuid import UUID, uuid4
from time import monotonic
import json
import getpass
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from labguard_server.db import get_db
from labguard_server.models import (AuditEvent, Device, DeviceAuthChallenge, DeviceCredential, DevicePosition,
                                    DeviceProcessRequest, DeviceStatus, DeviceStatusEvent, RdpAccessRequest, Room,
                                    SoftwareCatalogPackage, SoftwareJob, now_utc)
from labguard_server.schemas import (DeviceApproval, DeviceChallengeRequest, DeviceOut, DeviceTicketRequest, EnrollmentCodeOut, EnrollmentRequestIn,
                                     LayoutOut, LoginRequest, RoomCreate, RoomLayout, RoomOut, RoomPatch,
                                     RdpAccessRequestOut, SoftwareCatalogPackageCreate, SoftwareJobCreate,
                                     ProcessRequestCreate, ProcessRequestOut, WingetCatalogImport)
from labguard_server.security import csrf_protected, digest, require_role
from labguard_server.services import (approve_device, audit, authenticate, create_enrollment_code, create_room,
                                      create_device_challenge, delete_device, issue_device_ticket, save_layout, submit_enrollment,
                                      update_room)
from labguard_server.telemetry import latest_telemetry, telemetry_history, telemetry_summary
from labguard_server.peripheral_activity import peripheral_activity as get_peripheral_activity
from labguard_server.network_activity import network_activity
from labguard_server.wfp_activity import wfp_activity
from labguard_server.network_activity import _is_public_ip, _lookup_ipinfo
from labguard_server.software_inventory import (device_software_items, global_software_list, inventory_status,
                                                software_installations, software_summary)
from labguard_server.websocket import request_software_inventory_refresh
from labguard_server.websocket import send_rdp_access_request
from labguard_server.rdp_access import create_rdp_access_request, expire_rdp_request, rdp_request_out
from labguard_server.software_jobs import (catalog_out, create_software_job, dispatch_software_job,
                                           job_out)
from labguard_server.process_management import (create_process_request, expire_process_request,
                                                process_request_out)
from labguard_server.websocket import send_process_request
from labguard_server.winget_discovery import (WingetDiscoveryError, get_winget_package_metadata,
                                              get_winget_version, list_winget_sources, search_winget_packages)

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


@router.post("/devices/{device_id}/rdp/requests", response_model=RdpAccessRequestOut, status_code=202)
async def request_device_rdp(device_id: UUID, request: Request,
                             admin=Depends(require_role("LAB_ADMIN", csrf=True)),
                             db: Session = Depends(get_db)):
    if request.app.state.active_devices.get(device_id) is None:
        raise HTTPException(status_code=409, detail={"code": "device_offline", "message": "The device must be online to prepare RDP"})
    access_request = create_rdp_access_request(db, device_id, admin.id)
    sent = await send_rdp_access_request(request.app, device_id, {
        "request_id": str(access_request.id),
        "expires_at": access_request.expires_at.isoformat(),
        "access_expires_at": access_request.access_expires_at.isoformat(),
    })
    if not sent:
        current = db.get(RdpAccessRequest, access_request.id)
        if current is not None and current.status == "PENDING":
            current.status = "FAILED"
            current.error_code = "agent_unavailable"
            db.commit()
            db.refresh(current)
        access_request = current or access_request
    else:
        request.app.state.admin_events.publish({"type": "rdp.access", "request_id": str(access_request.id),
            "device_id": str(device_id), "status": "PENDING"})
    return rdp_request_out(access_request)


@router.get("/devices/{device_id}/rdp/requests/{request_id}", response_model=RdpAccessRequestOut)
def get_device_rdp_request(device_id: UUID, request_id: UUID,
                           _admin=Depends(require_role("LAB_ADMIN")), db: Session = Depends(get_db)):
    access_request = db.scalar(select(RdpAccessRequest).where(
        RdpAccessRequest.id == request_id, RdpAccessRequest.device_id == device_id))
    if access_request is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "RDP request not found"})
    return rdp_request_out(expire_rdp_request(db, access_request))


@router.post("/devices/{device_id}/process-requests", response_model=ProcessRequestOut, status_code=202)
async def request_device_process_operation(device_id: UUID, body: ProcessRequestCreate, request: Request,
                                           admin=Depends(require_role("LAB_ADMIN", csrf=True)),
                                           db: Session = Depends(get_db)):
    if request.app.state.active_devices.get(device_id) is None:
        raise HTTPException(status_code=409, detail={"code": "device_offline", "message": "The device must be online to inspect or manage processes"})
    process_request = create_process_request(db, device_id, admin.id, body)
    sent = await send_process_request(request.app, device_id, {
        "request_id": str(process_request.id), "operation": process_request.operation,
        "target_pid": process_request.target_pid,
        "target_created_at_us": process_request.target_created_at_us,
        "expires_at": process_request.expires_at.isoformat(),
    })
    if not sent:
        process_request.status = "FAILED"
        process_request.result_code = "agent_unavailable"
        process_request.completed_at = now_utc()
        db.commit()
        db.refresh(process_request)
    return process_request_out(process_request)


@router.get("/devices/{device_id}/process-requests/{request_id}", response_model=ProcessRequestOut)
def get_device_process_request(device_id: UUID, request_id: UUID,
                              _admin=Depends(require_role("LAB_ADMIN")), db: Session = Depends(get_db)):
    process_request = db.scalar(select(DeviceProcessRequest).where(
        DeviceProcessRequest.id == request_id,
        DeviceProcessRequest.device_id == device_id,
    ))
    if process_request is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Process request not found"})
    return process_request_out(expire_process_request(db, process_request))


@router.get("/devices/{device_id}/telemetry")
def device_telemetry(device_id: UUID, request: Request, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    return latest_telemetry(db, device_id, request.app.state.settings.telemetry_stale_after_seconds)


@router.get("/devices/{device_id}/telemetry/history")
def device_telemetry_history(device_id: UUID, request: Request, limit: int = Query(default=120, ge=1, le=500),
                             _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    return {"device_id": str(device_id), "samples": telemetry_history(
        db, device_id, limit, request.app.state.settings.telemetry_retention_days)}


@router.get("/devices/{device_id}/peripherals")
def device_peripherals(device_id: UUID, limit: int = Query(default=100, ge=1, le=500),
                       _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    return get_peripheral_activity(db, device_id, limit)


@router.get("/telemetry/summary")
def telemetry_overview(request: Request, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    return telemetry_summary(db, request.app.state.settings.telemetry_stale_after_seconds)


@router.get("/network/connections")
def network_connections(request: Request, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    return network_activity(db, request.app.state.settings.ipinfo_token)


@router.get("/network/events")
def network_events(request: Request, limit: int = Query(default=100, ge=1, le=500),
                   offset: int = Query(default=0, ge=0, le=1_000_000),
                   since_seconds: int | None = Query(default=None, ge=1, le=2_592_000),
                   device_id: UUID | None = None,
                   event_kind: str | None = Query(default=None, pattern=r"^(CONNECTION_ALLOWED|CONNECTION_BLOCKED|PACKET_BLOCKED)$"),
                   show_full_info: bool = False,
                   _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    result = wfp_activity(db, limit=limit, offset=offset, device_id=device_id,
                          event_kind=event_kind, public_only=not show_full_info,
                          since_seconds=since_seconds)
    token = request.app.state.settings.ipinfo_token
    addresses = list(dict.fromkeys(event["remote_ip"] for event in result["events"]
                                   if _is_public_ip(event["remote_ip"])))
    organizations = {}
    if token and addresses:
        with ThreadPoolExecutor(max_workers=min(20, len(addresses))) as pool:
            organizations.update(zip(addresses[:40], pool.map(lambda address: _lookup_ipinfo(address, token), addresses[:40])))
    for event in result["events"]:
        event["organization"] = organizations.get(event["remote_ip"])
    result["show_full_info"] = show_full_info
    result["lookups_enabled"] = bool(token)
    return result


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


@router.get("/devices/{device_id}/software")
def device_software(device_id: UUID, request: Request, search: str | None = Query(default=None, max_length=128),
                    publisher: str | None = Query(default=None, max_length=128),
                    source: str | None = Query(default=None, pattern=r"^(WINDOWS_REGISTRY|WINGET|CHOCO)$"),
                    installation_scope: str | None = Query(default=None, pattern=r"^(MACHINE|USER|UNKNOWN)$"),
                    version: str | None = Query(default=None, max_length=128),
                    offset: int = Query(default=0, ge=0, le=1_000_000), limit: int = Query(default=100, ge=1, le=200),
                    _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    items, total = device_software_items(db, device_id, search=search, publisher=publisher, source=source,
        installation_scope=installation_scope, version=version, offset=offset, limit=limit)
    return {"device_id": str(device_id), "collection": inventory_status(db, device_id,
            request.app.state.settings.software_inventory_stale_after_seconds),
            "items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/devices/{device_id}/software/refresh", status_code=202)
async def refresh_device_software(device_id: UUID, request: Request,
                                  admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    pending_refresh = request.app.state.software_refresh_requests.get(device_id)
    now = monotonic()
    cooldown = request.app.state.settings.software_inventory_refresh_cooldown_seconds
    if pending_refresh is not None and now - pending_refresh["requested_at"] < cooldown:
        retry = max(1, int(cooldown - (now - pending_refresh["requested_at"])))
        raise HTTPException(status_code=429, detail={"code": "refresh_rate_limited", "message": "Inventory refresh is on cooldown"},
                            headers={"Retry-After": str(retry)})
    request_id = uuid4()
    request.app.state.software_refresh_requests[device_id] = {
        "requested_at": now, "request_id": str(request_id),
    }
    if not await request_software_inventory_refresh(request.app, device_id, request_id):
        request.app.state.software_refresh_requests.pop(device_id, None)
        raise HTTPException(status_code=409, detail={"code": "device_offline", "message": "Device is offline or unavailable"})
    audit(db, admin.id, "software.inventory_refresh", "device", str(device_id), {"request_id": str(request_id)})
    db.commit()
    return {"device_id": str(device_id), "request_id": str(request_id), "status": "requested"}


@router.get("/software")
def list_software(search: str | None = Query(default=None, max_length=128), device_id: UUID | None = None,
                  publisher: str | None = Query(default=None, max_length=128),
                  source: str | None = Query(default=None, pattern=r"^(WINDOWS_REGISTRY|WINGET|CHOCO)$"),
                  installation_scope: str | None = Query(default=None, pattern=r"^(MACHINE|USER|UNKNOWN)$"),
                  version: str | None = Query(default=None, max_length=128),
                  offset: int = Query(default=0, ge=0, le=1_000_000), limit: int = Query(default=50, ge=1, le=200),
                  _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    items, total = global_software_list(db, search=search, device_id=device_id, publisher=publisher,
        source=source, installation_scope=installation_scope, version=version, offset=offset, limit=limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/software/summary")
def software_inventory_overview(request: Request, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    return software_summary(db, request.app.state.settings.software_inventory_stale_after_seconds)


@router.get("/software/catalog")
def list_software_catalog(search: str | None = Query(default=None, max_length=128),
                          package_manager: str | None = Query(default=None, pattern=r"^(WINGET|CHOCO)$"),
                          approved: bool | None = None, admin=Depends(require_role("VIEWER")),
                          db: Session = Depends(get_db)):
    query = select(SoftwareCatalogPackage)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(func.lower(SoftwareCatalogPackage.display_name).like(term.lower())
                            | func.lower(SoftwareCatalogPackage.package_id).like(term.lower())
                            | func.lower(SoftwareCatalogPackage.publisher).like(term.lower()))
    if package_manager:
        query = query.where(SoftwareCatalogPackage.package_manager == package_manager)
    if admin.role != "SUPER_ADMIN":
        query = query.where(SoftwareCatalogPackage.approved.is_(True))
    elif approved is not None:
        query = query.where(SoftwareCatalogPackage.approved.is_(approved))
    return [catalog_out(row) for row in db.scalars(query.order_by(SoftwareCatalogPackage.display_name)).all()]


@router.get("/software/discovery/status")
def winget_discovery_status(_admin=Depends(require_role("SUPER_ADMIN"))):
    try:
        return {"available": True, "version": get_winget_version(), "execution_identity": getpass.getuser(), "error": None}
    except WingetDiscoveryError as exc:
        return {"available": False, "version": None, "execution_identity": getpass.getuser(),
                "error": {"code": exc.code, "message": exc.message}}


@router.get("/software/discovery/sources")
def list_winget_repository_sources(_admin=Depends(require_role("SUPER_ADMIN"))):
    try:
        version, sources = list_winget_sources()
    except WingetDiscoveryError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    return {"winget_version": version, "sources": [source.as_dict() for source in sources]}


@router.get("/software/discovery/search")
def search_winget_repository(query: str = Query(min_length=1, max_length=128),
                             source: str = Query(default="winget", min_length=1, max_length=64,
                                                 pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
                             _admin=Depends(require_role("LAB_ADMIN"))):
    if source.casefold() != "winget":
        raise HTTPException(status_code=422, detail={"code": "winget_source_not_deployable",
                           "message": "Deployment searches are restricted to the fixed winget community source"})
    try:
        version, packages = search_winget_packages(query, source)
    except WingetDiscoveryError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    return {"source": "winget", "winget_version": version, "results": [package.as_dict() for package in packages]}


@router.get("/software/discovery/package/{package_id}")
def get_winget_repository_package(package_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$"),
                                 _admin=Depends(require_role("LAB_ADMIN"))):
    try:
        metadata = get_winget_package_metadata(package_id, "winget")
    except WingetDiscoveryError as exc:
        status = 422 if exc.code.startswith("invalid_") or exc.code.endswith("mismatch") else 503
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    return {**metadata, "source": "winget"}


@router.post("/software/discovery/import", status_code=201)
def import_winget_discovery(body: WingetCatalogImport, request: Request,
                            admin=Depends(require_role("SUPER_ADMIN", csrf=True)),
                            db: Session = Depends(get_db)):
    # Existing client jobs deliberately accept only the v0.6 community source.
    # Keep discovery from creating approved entries that the agent cannot execute faithfully.
    if body.source.casefold() != "winget":
        raise HTTPException(status_code=422, detail={"code": "winget_source_not_deployable",
                           "message": "Only packages from the configured winget source can be added to the deployable catalog"})
    existing = db.scalar(select(SoftwareCatalogPackage).where(
        SoftwareCatalogPackage.package_manager == "WINGET",
        func.lower(SoftwareCatalogPackage.package_id) == body.package_id.lower()))
    if existing is not None:
        return {"package": catalog_out(existing), "created": False}
    try:
        metadata = get_winget_package_metadata(body.package_id, body.source)
    except WingetDiscoveryError as exc:
        status = 422 if exc.code.startswith("invalid_") else 503
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    package = SoftwareCatalogPackage(
        display_name=metadata["display_name"], package_id=body.package_id,
        package_manager="WINGET", publisher=metadata["publisher"], description=metadata["description"],
        version_policy="LATEST", approved_version=None, supported_scopes=body.supported_scopes,
        source="WINGET_COMMUNITY", approved=False, approval_status="PENDING", created_by=admin.id,
    )
    db.add(package)
    db.flush()
    audit(db, admin.id, "software.catalog.discover", "software_package", str(package.id),
          {"package_id": package.package_id, "source": body.source})
    db.commit()
    db.refresh(package)
    request.app.state.admin_events.publish({"type": "software.catalog", "package_id": str(package.id)})
    return {"package": catalog_out(package), "created": True}


@router.post("/software/catalog", status_code=201)
def create_software_catalog_package(body: SoftwareCatalogPackageCreate,
                                    request: Request,
                                    admin=Depends(require_role("SUPER_ADMIN", csrf=True)),
                                    db: Session = Depends(get_db)):
    if body.package_manager == "CHOCO" and not request.app.state.settings.chocolatey_source_url:
        raise HTTPException(status_code=503, detail={"code": "chocolatey_source_unconfigured", "message": "Configure CHOCOLATEY_SOURCE_URL before adding Chocolatey packages"})
    existing = db.scalar(select(SoftwareCatalogPackage).where(
        SoftwareCatalogPackage.package_manager == body.package_manager,
        func.lower(SoftwareCatalogPackage.package_id) == body.package_id.lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "package_exists", "message": "This package is already in the catalog"})
    package = SoftwareCatalogPackage(**body.model_dump(), source=(
        "WINGET_COMMUNITY" if body.package_manager == "WINGET" else "CHOCO_CONFIGURED"),
        approved=False, approval_status="PENDING", created_by=admin.id)
    db.add(package)
    audit(db, admin.id, "software.catalog.create", "software_package", str(package.id),
          {"package_id": package.package_id, "package_manager": package.package_manager})
    db.commit()
    db.refresh(package)
    return catalog_out(package)


@router.post("/software/catalog/{package_id}/approve")
def approve_software_catalog_package(package_id: UUID, request: Request,
                                     admin=Depends(require_role("SUPER_ADMIN", csrf=True)),
                                     db: Session = Depends(get_db)):
    package = db.scalar(select(SoftwareCatalogPackage).where(
        SoftwareCatalogPackage.id == package_id).with_for_update())
    if package is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Catalog package not found"})
    if package.package_manager == "CHOCO" and not package.approved and not request.app.state.settings.chocolatey_source_url:
        raise HTTPException(status_code=503, detail={"code": "chocolatey_source_unconfigured", "message": "Configure CHOCOLATEY_SOURCE_URL before approving Chocolatey packages"})
    if not package.approved:
        package.approved = True
        package.approval_status = "APPROVED"
        package.approved_at = now_utc()
        audit(db, admin.id, "software.catalog.approve", "software_package", str(package.id),
              {"package_id": package.package_id, "package_manager": package.package_manager})
        db.commit()
    return catalog_out(package)


@router.post("/software/catalog/{package_id}/revoke")
def revoke_software_catalog_package(package_id: UUID, admin=Depends(require_role("SUPER_ADMIN", csrf=True)),
                                    db: Session = Depends(get_db)):
    package = db.scalar(select(SoftwareCatalogPackage).where(
        SoftwareCatalogPackage.id == package_id).with_for_update())
    if package is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Catalog package not found"})
    if package.approved:
        package.approved = False
        package.approval_status = "REVOKED"
        package.approved_at = None
        audit(db, admin.id, "software.catalog.revoke", "software_package", str(package.id),
              {"package_id": package.package_id, "package_manager": package.package_manager})
        db.commit()
    return catalog_out(package)


@router.post("/software/catalog/{package_id}/reject")
def reject_software_catalog_package(package_id: UUID,
                                    admin=Depends(require_role("SUPER_ADMIN", csrf=True)),
                                    db: Session = Depends(get_db)):
    package = db.scalar(select(SoftwareCatalogPackage).where(
        SoftwareCatalogPackage.id == package_id).with_for_update())
    if package is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Catalog package not found"})
    if package.approved:
        raise HTTPException(status_code=409, detail={"code": "package_already_approved", "message": "Revoke approval before rejecting this package"})
    if package.approval_status != "REJECTED":
        package.approval_status = "REJECTED"
        package.approved_at = None
        audit(db, admin.id, "software.catalog.reject", "software_package", str(package.id),
              {"package_id": package.package_id, "package_manager": package.package_manager})
        db.commit()
    return catalog_out(package)


@router.post("/devices/{device_id}/software/jobs", status_code=202)
async def create_device_software_job(device_id: UUID, body: SoftwareJobCreate, request: Request,
                                     admin=Depends(require_role("LAB_ADMIN", csrf=True)),
                                     db: Session = Depends(get_db)):
    direct_winget = None
    if body.action == "INSTALL" and body.catalog_package_id is None:
        if body.package_manager != "WINGET" or body.source is None or body.source.casefold() != "winget" or body.package_id is None:
            raise HTTPException(status_code=422, detail={"code": "invalid_direct_package", "message": "Direct installation is restricted to exact WinGet package IDs from the winget source"})
        try:
            direct_winget = get_winget_package_metadata(body.package_id, "winget", body.version)
        except WingetDiscoveryError as exc:
            status = 422 if exc.code.startswith("invalid_") or exc.code.endswith("mismatch") or exc.code == "version_not_found" else 503
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    job = create_software_job(db, device_id, admin.id, body,
        choco_source_configured=bool(request.app.state.settings.chocolatey_source_url),
        direct_winget=direct_winget)
    audit(db, admin.id, "software.job_requested", "software_job", str(job.id), {
        "device_id": str(device_id), "action": job.action, "package_id": job.package_id,
        "package_manager": job.package_manager,
    })
    db.commit()
    await dispatch_software_job(request.app, job.id)
    refreshed = db.get(SoftwareJob, job.id)
    request.app.state.admin_events.publish({"type": "software.job", "job_id": str(job.id),
        "device_id": str(device_id), "status": refreshed.status})
    return job_out(refreshed)


@router.get("/software/jobs")
def list_software_jobs(status: str | None = Query(default=None, pattern=r"^(PENDING|DISPATCHED|RUNNING|SUCCEEDED|FAILED|CANCELLED|EXPIRED)$"),
                       device_id: UUID | None = None, offset: int = Query(default=0, ge=0, le=1_000_000),
                       limit: int = Query(default=50, ge=1, le=200),
                       _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    query = select(SoftwareJob)
    if status:
        query = query.where(SoftwareJob.status == status)
    if device_id:
        query = query.where(SoftwareJob.device_id == device_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    jobs = db.scalars(query.order_by(SoftwareJob.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [job_out(job) for job in jobs], "total": total, "offset": offset, "limit": limit}


@router.get("/devices/{device_id}/software/jobs")
def list_device_software_jobs(device_id: UUID, offset: int = Query(default=0, ge=0, le=1_000_000),
                              limit: int = Query(default=50, ge=1, le=200),
                              _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    query = select(SoftwareJob).where(SoftwareJob.device_id == device_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    jobs = db.scalars(query.order_by(SoftwareJob.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [job_out(job) for job in jobs], "total": total, "offset": offset, "limit": limit}


@router.get("/software/jobs/{job_id}")
def get_software_job(job_id: UUID, _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    job = db.get(SoftwareJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Software job not found"})
    return job_out(job)


@router.get("/software/{software_key}/installations")
def list_software_installations(software_key: str = Path(pattern=r"^[0-9a-f]{64}$"),
                                offset: int = Query(default=0, ge=0, le=1_000_000),
                                limit: int = Query(default=200, ge=1, le=500),
                                _admin=Depends(require_role("VIEWER")), db: Session = Depends(get_db)):
    items, total = software_installations(db, software_key, offset=offset, limit=limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.delete("/devices/{device_id}", status_code=204)
async def remove_device(device_id: UUID, request: Request,
                        admin=Depends(require_role("LAB_ADMIN", csrf=True)), db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    active = request.app.state.active_devices.get(device_id)
    delete_device(db, admin.id, device)
    if active is not None:
        if request.app.state.active_devices.get(device_id) is active:
            request.app.state.active_devices.pop(device_id, None)
            request.app.state.active_device_send_locks.pop(device_id, None)
        try:
            await active.close(code=4404, reason="device_deleted")
        except RuntimeError:
            pass
    request.app.state.admin_events.publish({"type": "device.deleted", "device_id": str(device_id)})
    return Response(status_code=204)


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
