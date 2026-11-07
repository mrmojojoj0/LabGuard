from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.models import (Device, DeviceCredential, DeviceStatus, SoftwareCatalogPackage,
                                   SoftwareInventoryItem, SoftwareJob, now_utc)
from labguard_server.schemas import SoftwareJobCreate, SoftwareJobEventIn
from labguard_server.winget_discovery import PACKAGE_ID_RE

ACTIVE_JOB_STATES = ("PENDING", "DISPATCHED", "RUNNING")
TERMINAL_JOB_STATES = ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")


def _is_expired(value, now) -> bool:
    # SQLite returns timezone-aware columns as naive datetimes even when the
    # schema was declared timezone=True. Normalize at the Python comparison.
    if value.tzinfo is None:
        value = value.replace(tzinfo=now.tzinfo)
    return value < now


def catalog_out(package: SoftwareCatalogPackage) -> dict:
    return {
        "id": str(package.id), "display_name": package.display_name, "package_id": package.package_id,
        "package_manager": package.package_manager, "publisher": package.publisher,
        "description": package.description, "version_policy": package.version_policy,
        "approved_version": package.approved_version, "supported_scopes": package.supported_scopes,
        "source": package.source, "approved": package.approved,
        "approval_status": package.approval_status,
        "created_at": package.created_at.isoformat(),
        "approved_at": package.approved_at.isoformat() if package.approved_at else None,
    }


def job_out(job: SoftwareJob) -> dict:
    return {
        "id": str(job.id), "device_id": str(job.device_id),
        "catalog_package_id": str(job.catalog_package_id) if job.catalog_package_id else None,
        "requested_by": str(job.requested_by) if job.requested_by else None,
        "action": job.action, "package_id": job.package_id, "package_manager": job.package_manager,
        "requested_version": job.requested_version, "installation_scope": job.installation_scope,
        "source": job.source, "status": job.status, "progress_percent": job.progress_percent,
        "progress_message": job.progress_message, "result_code": job.result_code,
        "result_summary": job.result_summary, "error_message": job.error_message,
        "created_at": job.created_at.isoformat(), "expires_at": job.expires_at.isoformat(),
        "dispatched_at": job.dispatched_at.isoformat() if job.dispatched_at else None,
        "accepted_at": job.accepted_at.isoformat() if job.accepted_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def create_software_job(db: Session, device_id: UUID, requested_by: UUID, body: SoftwareJobCreate,
                        *, choco_source_configured: bool, direct_winget: dict | None = None) -> SoftwareJob:
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    if status is None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=409, detail={"code": "device_unavailable", "message": "Device is not approved and enabled"})
    package = db.get(SoftwareCatalogPackage, body.catalog_package_id) if body.catalog_package_id else None
    version = None
    inventory_item = None
    if body.action == "INSTALL":
        if package is not None:
            if not package.approved:
                raise HTTPException(status_code=409, detail={"code": "package_not_approved", "message": "Select an approved catalog package"})
            if package.package_manager == "CHOCO" and not choco_source_configured:
                raise HTTPException(status_code=503, detail={"code": "chocolatey_source_unconfigured", "message": "Chocolatey source is not configured"})
            if body.installation_scope not in package.supported_scopes:
                raise HTTPException(status_code=422, detail={"code": "unsupported_scope", "message": "Package does not support that installation scope"})
            if package.version_policy == "PINNED":
                if body.version is not None and body.version != package.approved_version:
                    raise HTTPException(status_code=422, detail={"code": "version_not_approved", "message": "Only the approved package version can be installed"})
                version = package.approved_version
            elif package.version_policy == "SELECTABLE":
                if body.version is None:
                    raise HTTPException(status_code=422, detail={"code": "version_required", "message": "Choose a package version"})
                version = body.version
            elif body.version is not None:
                raise HTTPException(status_code=422, detail={"code": "version_not_selectable", "message": "This package is configured to use its latest version"})
            package_id, manager, source = package.package_id, package.package_manager, package.source
        else:
            if direct_winget is None or body.package_manager != "WINGET" or not body.package_id or not body.source:
                raise HTTPException(status_code=422, detail={"code": "invalid_direct_package", "message": "A validated WinGet search result is required"})
            if body.source.casefold() != "winget" or not PACKAGE_ID_RE.fullmatch(body.package_id):
                raise HTTPException(status_code=422, detail={"code": "invalid_direct_package", "message": "WinGet package ID or source is invalid"})
            if direct_winget.get("package_id", "").casefold() != body.package_id.casefold():
                raise HTTPException(status_code=422, detail={"code": "package_identity_mismatch", "message": "WinGet package identity could not be verified"})
            verified_version = direct_winget.get("version")
            if body.version is not None and (not verified_version or body.version != verified_version):
                raise HTTPException(status_code=422, detail={"code": "version_not_found", "message": "The selected version could not be verified from WinGet"})
            version = body.version
            if body.installation_scope not in {"MACHINE", "USER"}:
                raise HTTPException(status_code=422, detail={"code": "unsupported_scope", "message": "WinGet scope is invalid"})
            package_id, manager, source = body.package_id, "WINGET", "WINGET_COMMUNITY"
    else:
        inventory_item = db.get(SoftwareInventoryItem, body.inventory_item_id)
        if inventory_item is None or inventory_item.device_id != device_id or not inventory_item.is_present:
            raise HTTPException(status_code=409, detail={"code": "installation_unavailable", "message": "The selected installation is no longer present on this device"})
        if inventory_item.source not in {"WINGET", "CHOCO"} or not inventory_item.package_id or not PACKAGE_ID_RE.fullmatch(inventory_item.package_id):
            raise HTTPException(status_code=409, detail={"code": "uninstall_unsupported", "message": "This inventory entry does not have a safely validated package identity"})
        manager = "WINGET" if inventory_item.source == "WINGET" else "CHOCO"
        package_id = inventory_item.package_id
        source = "WINGET_COMMUNITY" if manager == "WINGET" else "CHOCO_CONFIGURED"
        if (manager == "WINGET" and inventory_item.installation_scope not in {"MACHINE", "USER"}
                or manager == "CHOCO" and inventory_item.installation_scope != "MACHINE"):
            raise HTTPException(status_code=409, detail={"code": "uninstall_unsupported", "message": "This installed scope is not supported by the package manager"})
        if package is not None:
            if not package.approved or package.package_manager != manager:
                raise HTTPException(status_code=409, detail={"code": "package_not_approved", "message": "The selected catalog package is not available"})
            if package.package_id.casefold() != package_id.casefold():
                raise HTTPException(status_code=409, detail={"code": "catalog_identity_mismatch", "message": "Installed package does not match the catalog identity"})
            if inventory_item.installation_scope not in package.supported_scopes:
                raise HTTPException(status_code=409, detail={"code": "unsupported_scope", "message": "This installed scope is not supported by the catalog package"})
        if manager == "CHOCO" and (inventory_item.installation_scope != "MACHINE" or not choco_source_configured):
            raise HTTPException(status_code=409, detail={"code": "uninstall_unsupported", "message": "Chocolatey uninstall requires a configured machine-scope installation"})

    active = db.scalar(select(SoftwareJob.id).where(
        SoftwareJob.device_id == device_id, SoftwareJob.status.in_(ACTIVE_JOB_STATES),
    ).with_for_update().limit(1))
    if active is not None:
        raise HTTPException(status_code=409, detail={"code": "device_job_active", "message": "This device already has an active software job"})

    now = now_utc()
    job = SoftwareJob(
        device_id=device_id, catalog_package_id=package.id if package else None, requested_by=requested_by,
        action=body.action, package_id=package_id, package_manager=manager,
        requested_version=version,
        installation_scope=inventory_item.installation_scope if inventory_item else body.installation_scope,
        source=source, status="PENDING", progress_percent=0,
        expires_at=now + timedelta(seconds=body.expires_in_seconds),
    )
    db.add(job)
    db.flush()
    return job


def record_software_job_event(db: Session, device_id: UUID, sequence: int, event_type: str,
                              payload: SoftwareJobEventIn) -> tuple[dict, bool]:
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (status is None or device is None or credential is None or credential.revoked_at is not None
            or not device.enabled or device.enrollment_state != "APPROVED"):
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return {"accepted": False, "reason": "replayed_sequence"}, False
    status.last_sequence = sequence
    job = db.scalar(select(SoftwareJob).where(
        SoftwareJob.id == payload.job_id, SoftwareJob.device_id == device_id,
    ).with_for_update())
    if job is None:
        db.commit()
        return {"accepted": False, "reason": "job_not_found"}, False
    now = now_utc()
    if job.status in TERMINAL_JOB_STATES:
        db.commit()
        return {"accepted": False, "reason": "job_already_terminal", "status": job.status}, False
    if _is_expired(job.expires_at, now) and job.status in ("PENDING", "DISPATCHED"):
        job.status = "EXPIRED"
        job.completed_at = now
        job.error_message = "Job expired before it began"
        db.commit()
        return {"accepted": False, "reason": "job_expired", "status": job.status}, False

    if event_type == "client.job.accepted":
        if job.status != "DISPATCHED":
            db.commit()
            return {"accepted": False, "reason": "invalid_job_state", "status": job.status}, False
        job.accepted_at = job.accepted_at or now
    elif event_type == "client.job.started":
        if job.status != "DISPATCHED":
            db.commit()
            return {"accepted": False, "reason": "invalid_job_state", "status": job.status}, False
        job.status = "RUNNING"
        job.started_at = now
        job.progress_percent = max(job.progress_percent, 1)
        job.progress_message = "Running approved package operation"
    elif event_type == "client.job.progress":
        if job.status != "RUNNING":
            db.commit()
            return {"accepted": False, "reason": "invalid_job_state", "status": job.status}, False
        if payload.progress_percent is not None:
            job.progress_percent = max(job.progress_percent, payload.progress_percent)
        if payload.progress_message is not None:
            job.progress_message = payload.progress_message
    elif event_type == "client.job.completed":
        if job.status != "RUNNING":
            db.commit()
            return {"accepted": False, "reason": "invalid_job_state", "status": job.status}, False
        job.status = "SUCCEEDED" if payload.result_code == "verified_success" else "FAILED"
        job.completed_at = now
        job.progress_percent = 100 if job.status == "SUCCEEDED" else job.progress_percent
        job.result_code = payload.result_code
        job.result_summary = payload.result_summary
        job.error_message = payload.error_message
    elif event_type == "client.job.failed":
        if job.status != "RUNNING":
            db.commit()
            return {"accepted": False, "reason": "invalid_job_state", "status": job.status}, False
        job.status = "FAILED"
        job.completed_at = now
        job.result_code = payload.result_code or "execution_failed"
        job.result_summary = payload.result_summary
        job.error_message = payload.error_message
    else:
        db.commit()
        return {"accepted": False, "reason": "unsupported_job_event"}, False
    db.commit()
    return {"accepted": True, "status": job.status}, job.status in TERMINAL_JOB_STATES


def software_job_allows_inventory(db: Session, device_id: UUID, job_id: UUID) -> bool:
    return db.scalar(select(SoftwareJob.id).where(
        SoftwareJob.id == job_id, SoftwareJob.device_id == device_id,
        SoftwareJob.status == "RUNNING",
    )) is not None


def expire_software_jobs(db: Session) -> int:
    now = now_utc()
    jobs = db.scalars(select(SoftwareJob).where(
        SoftwareJob.status.in_(("PENDING", "DISPATCHED")), SoftwareJob.expires_at < now,
    )).all()
    for job in jobs:
        job.status = "EXPIRED"
        job.completed_at = now
        job.error_message = "Job expired before it began"
    if jobs:
        db.commit()
    return len(jobs)


def job_offer_payload(job: SoftwareJob, application) -> dict:
    settings = application.state.settings
    source_url = settings.chocolatey_source_url if job.package_manager == "CHOCO" else None
    return {
        "job_id": str(job.id), "action": job.action, "package_id": job.package_id,
        "package_manager": job.package_manager, "version": job.requested_version,
        "installation_scope": job.installation_scope, "source": job.source,
        "source_url": source_url, "expires_at": job.expires_at.isoformat(),
        "timeout_seconds": settings.software_job_max_runtime_seconds,
    }


async def dispatch_software_job(application, job_id: UUID) -> bool:
    with application.state.session_factory() as db:
        job = db.scalar(select(SoftwareJob).where(SoftwareJob.id == job_id).with_for_update())
        if job is None or job.status in TERMINAL_JOB_STATES:
            return False
        if application.state.active_devices.get(job.device_id) is None:
            return False
        if _is_expired(job.expires_at, now_utc()) and job.status in ("PENDING", "DISPATCHED"):
            job.status = "EXPIRED"
            job.completed_at = now_utc()
            job.error_message = "Job expired before it began"
            db.commit()
            return False
        if job.status not in ("PENDING", "DISPATCHED", "RUNNING"):
            return False
        if job.status == "PENDING":
            job.status = "DISPATCHED"
            job.dispatched_at = now_utc()
        payload = job_offer_payload(job, application)
        device_id = job.device_id
        db.commit()
    websocket = application.state.active_devices.get(device_id)
    if websocket is None:
        return False
    from labguard_server.websocket import send_software_job_offer
    return await send_software_job_offer(application, device_id, payload)


async def dispatch_pending_software_jobs(application, device_id: UUID) -> None:
    with application.state.session_factory() as db:
        expire_software_jobs(db)
        ids = db.scalars(select(SoftwareJob.id).where(
            SoftwareJob.device_id == device_id,
            SoftwareJob.status.in_(("PENDING", "DISPATCHED", "RUNNING")),
            SoftwareJob.expires_at > now_utc(),
        ).order_by(SoftwareJob.created_at)).all()
    for job_id in ids:
        if not await dispatch_software_job(application, job_id):
            break


async def software_job_monitor(application) -> None:
    while True:
        with application.state.session_factory() as db:
            expiring = db.scalars(select(SoftwareJob).where(
                SoftwareJob.status.in_(("PENDING", "DISPATCHED")),
                SoftwareJob.expires_at < now_utc(),
            )).all()
            expired = expire_software_jobs(db)
            running = db.scalars(select(SoftwareJob).where(
                SoftwareJob.status == "RUNNING",
                SoftwareJob.started_at < now_utc() - timedelta(seconds=application.state.settings.software_job_max_runtime_seconds + 30),
            )).all()
            for job in running:
                job.status = "FAILED"
                job.completed_at = now_utc()
                job.result_code = "server_timeout"
                job.error_message = "Agent did not report a result before the job timeout"
            if running:
                db.commit()
            if expired or running:
                for job in [*expiring, *running]:
                    application.state.admin_events.publish({"type": "software.job", "job_id": str(job.id),
                        "device_id": str(job.device_id), "status": job.status})
        await asyncio.sleep(10)
