from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from labguard_server.models import (Device, DeviceCredential, DeviceStatus, SoftwareInventoryBatchReceipt,
    SoftwareInventoryCollection, SoftwareInventoryItem, now_utc)
from labguard_server.schemas import SoftwareInventoryBatchIn


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def record_software_inventory_batch(db: Session, device_id: UUID, sequence: int,
                                    payload: SoftwareInventoryBatchIn, min_interval_seconds: float,
                                    retention_days: int, manual_refresh_authorized: bool = False,
                                    job_refresh_authorized: bool = False) -> tuple[dict, bool]:
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if (status is None or device is None or credential is None or credential.revoked_at is not None
            or not device.enabled or device.enrollment_state != "APPROVED"):
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return {"accepted": False, "reason": "replayed_sequence"}, False
    status.last_sequence = sequence
    now = now_utc()
    if _utc(payload.started_at) > now + timedelta(minutes=5):
        db.commit()
        return {"accepted": False, "reason": "collection_time_in_future"}, False

    if (db.get(SoftwareInventoryCollection, payload.collection_id) is None
            and not manual_refresh_authorized and not job_refresh_authorized):
        recent = db.scalar(select(SoftwareInventoryCollection).where(
            SoftwareInventoryCollection.device_id == device_id,
            SoftwareInventoryCollection.received_at > now - timedelta(seconds=min_interval_seconds),
        ).order_by(SoftwareInventoryCollection.received_at.desc()).limit(1))
        if recent is not None:
            db.commit()
            return {"accepted": False, "reason": "inventory_rate_limited"}, False

    if payload.unchanged:
        previous = db.scalar(select(SoftwareInventoryCollection).where(
            SoftwareInventoryCollection.device_id == device_id,
            SoftwareInventoryCollection.status.in_(("COMPLETE", "UNCHANGED")),
        ).order_by(SoftwareInventoryCollection.completed_at.desc()).limit(1))
        if previous is None or previous.inventory_digest != payload.inventory_digest:
            db.commit()
            return {"accepted": False, "reason": "inventory_digest_mismatch", "full_refresh_required": True}, False
        count = db.scalar(select(func.count()).select_from(SoftwareInventoryItem).where(
            SoftwareInventoryItem.device_id == device_id, SoftwareInventoryItem.is_present)) or 0
        db.add(SoftwareInventoryCollection(id=payload.collection_id, device_id=device_id,
            request_id=payload.request_id, started_at=_utc(payload.started_at), received_at=now, completed_at=now,
            job_id=payload.job_id,
            status="UNCHANGED", expected_batches=1, received_batches=1, discovered_count=count,
            errors=[], inventory_digest=payload.inventory_digest))
        db.execute(delete(SoftwareInventoryCollection).where(
            SoftwareInventoryCollection.device_id == device_id,
            SoftwareInventoryCollection.completed_at < now - timedelta(days=retention_days),
        ), execution_options={"synchronize_session": False})
        db.commit()
        return {"accepted": True, "reason": "unchanged", "completed": True, "status": "UNCHANGED"}, True

    collection = db.get(SoftwareInventoryCollection, payload.collection_id)
    if collection is None:
        collection = SoftwareInventoryCollection(id=payload.collection_id, device_id=device_id,
            request_id=payload.request_id, job_id=payload.job_id,
            started_at=_utc(payload.started_at), received_at=now, completed_at=None,
            status="IN_PROGRESS", expected_batches=payload.batch_count, received_batches=0,
            discovered_count=0, errors=payload.errors, inventory_digest=payload.inventory_digest)
        db.add(collection)
        # A disconnected prior transfer cannot safely be treated as a successful scan.
        db.query(SoftwareInventoryCollection).filter(
            SoftwareInventoryCollection.device_id == device_id,
            SoftwareInventoryCollection.status == "IN_PROGRESS",
            SoftwareInventoryCollection.id != payload.collection_id,
        ).update({"status": "FAILED", "completed_at": now,
                  "errors": ["superseded_by_new_collection"]}, synchronize_session=False)
        db.flush()
        db.execute(delete(SoftwareInventoryCollection).where(
            SoftwareInventoryCollection.device_id == device_id,
            SoftwareInventoryCollection.completed_at < now - timedelta(days=retention_days),
        ), execution_options={"synchronize_session": False})
    elif collection.device_id != device_id:
        db.commit()
        return {"accepted": False, "reason": "collection_not_owned"}, False
    elif collection.status != "IN_PROGRESS":
        db.commit()
        return {"accepted": False, "reason": "collection_already_completed"}, False
    elif (collection.expected_batches != payload.batch_count or collection.inventory_digest != payload.inventory_digest
          or collection.request_id != payload.request_id or collection.job_id != payload.job_id
          or collection.status == "IN_PROGRESS" and collection.errors != payload.errors):
        db.commit()
        return {"accepted": False, "reason": "collection_metadata_mismatch"}, False

    receipt = db.get(SoftwareInventoryBatchReceipt, (payload.collection_id, payload.batch_index))
    if receipt is not None:
        db.commit()
        return {"accepted": True, "reason": "duplicate_batch", "completed": False}, False

    keys = [entry.entry_key for entry in payload.entries]
    existing = db.scalars(select(SoftwareInventoryItem).where(
        SoftwareInventoryItem.device_id == device_id, SoftwareInventoryItem.entry_key.in_(keys),
    ).with_for_update()).all() if keys else []
    by_key = {item.entry_key: item for item in existing}
    for entry in payload.entries:
        values = entry.model_dump()
        product_source = f"{entry.name.casefold().strip()}\x1f{(entry.publisher or '').casefold().strip()}"
        product_key = hashlib.sha256(product_source.encode("utf-8")).hexdigest()
        item = by_key.get(entry.entry_key)
        if item is None:
            item = SoftwareInventoryItem(device_id=device_id, product_key=product_key,
                first_seen_at=now, **values, last_seen_at=now,
                is_present=True, missing_since=None, last_collection_id=collection.id)
            db.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
            item.product_key = product_key
            item.last_seen_at = now
            item.is_present = True
            item.missing_since = None
            item.last_collection_id = collection.id
    db.add(SoftwareInventoryBatchReceipt(collection_id=payload.collection_id,
        batch_index=payload.batch_index, item_count=len(payload.entries)))
    collection.received_batches += 1
    if collection.received_batches >= collection.expected_batches:
        collection.completed_at = now
        collection.status = payload.collection_status
        collection.errors = payload.errors
        collection.discovered_count = db.scalar(select(func.count()).select_from(SoftwareInventoryItem).where(
            SoftwareInventoryItem.device_id == device_id,
            SoftwareInventoryItem.last_collection_id == collection.id)) or 0
        if collection.status == "COMPLETE" and not collection.errors:
            db.query(SoftwareInventoryItem).filter(
                SoftwareInventoryItem.device_id == device_id,
                SoftwareInventoryItem.is_present.is_(True),
                SoftwareInventoryItem.last_collection_id != collection.id,
            ).update({"is_present": False, "missing_since": now}, synchronize_session=False)
    db.commit()
    return {"accepted": True, "reason": None, "completed": collection.completed_at is not None,
            "status": collection.status}, collection.completed_at is not None


def inventory_status(db: Session, device_id: UUID, stale_after_seconds: int = 48 * 3600) -> dict:
    latest = db.scalar(select(SoftwareInventoryCollection).where(
        SoftwareInventoryCollection.device_id == device_id,
    ).order_by(SoftwareInventoryCollection.started_at.desc()).limit(1))
    successful = db.scalar(select(SoftwareInventoryCollection).where(
        SoftwareInventoryCollection.device_id == device_id,
        SoftwareInventoryCollection.status.in_(("COMPLETE", "UNCHANGED", "PARTIAL")),
    ).order_by(SoftwareInventoryCollection.completed_at.desc()).limit(1))
    complete = db.scalar(select(SoftwareInventoryCollection).where(
        SoftwareInventoryCollection.device_id == device_id,
        SoftwareInventoryCollection.status.in_(("COMPLETE", "UNCHANGED")),
    ).order_by(SoftwareInventoryCollection.completed_at.desc()).limit(1))
    if latest is None:
        return {"status": "NEVER", "started_at": None, "completed_at": None,
                "last_attempt_at": None, "last_attempt_status": "NEVER",
                "last_successful_at": None, "last_complete_at": None,
                "discovered_count": 0, "errors": [], "stale": True}
    successful_at = _utc(successful.completed_at) if successful and successful.completed_at else None
    is_stale = successful_at is None or (now_utc() - successful_at).total_seconds() > stale_after_seconds
    return {"collection_id": str(latest.id), "request_id": str(latest.request_id) if latest.request_id else None,
            "status": latest.status, "started_at": latest.started_at.isoformat(),
            "last_attempt_at": latest.started_at.isoformat(), "last_attempt_status": latest.status,
            "completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
            "last_successful_at": successful.completed_at.isoformat() if successful and successful.completed_at else None,
            "last_complete_at": complete.completed_at.isoformat() if complete and complete.completed_at else None,
            "discovered_count": latest.discovered_count, "errors": latest.errors or [], "stale": is_stale}


def device_software_items(db: Session, device_id: UUID, *, search: str | None = None,
                          publisher: str | None = None, source: str | None = None,
                          installation_scope: str | None = None, version: str | None = None,
                          software_key: str | None = None, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    query = select(SoftwareInventoryItem).where(
        SoftwareInventoryItem.device_id == device_id, SoftwareInventoryItem.is_present.is_(True))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(SoftwareInventoryItem.name.ilike(term), SoftwareInventoryItem.publisher.ilike(term)))
    if publisher:
        query = query.where(SoftwareInventoryItem.publisher.ilike(f"%{publisher.strip()}%"))
    if source:
        query = query.where(SoftwareInventoryItem.source == source)
    if installation_scope:
        query = query.where(SoftwareInventoryItem.installation_scope == installation_scope)
    if version:
        query = query.where(SoftwareInventoryItem.version == version)
    if software_key:
        query = query.where(SoftwareInventoryItem.product_key == software_key)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(SoftwareInventoryItem.name, SoftwareInventoryItem.version)
                      .offset(offset).limit(limit)).all()
    return [_item_out(row) for row in rows], total


def _item_out(row: SoftwareInventoryItem) -> dict:
    return {"id": str(row.id), "device_id": str(row.device_id), "software_key": row.product_key,
            "entry_key": row.entry_key, "name": row.name, "version": row.version,
            "publisher": row.publisher, "architecture": row.architecture,
            "install_date": row.install_date, "install_location": row.install_location,
            "package_id": row.package_id, "source": row.source,
            "installation_scope": row.installation_scope,
            "first_seen_at": row.first_seen_at.isoformat(), "last_seen_at": row.last_seen_at.isoformat()}


def global_software_list(db: Session, *, search: str | None = None, device_id: UUID | None = None,
                         publisher: str | None = None, source: str | None = None,
                         installation_scope: str | None = None, version: str | None = None,
                         offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    conditions = [SoftwareInventoryItem.is_present.is_(True)]
    if device_id:
        conditions.append(SoftwareInventoryItem.device_id == device_id)
    if search:
        term = f"%{search.strip()}%"
        conditions.append(or_(SoftwareInventoryItem.name.ilike(term), SoftwareInventoryItem.publisher.ilike(term)))
    if publisher:
        conditions.append(SoftwareInventoryItem.publisher.ilike(f"%{publisher.strip()}%"))
    if source:
        conditions.append(SoftwareInventoryItem.source == source)
    if installation_scope:
        conditions.append(SoftwareInventoryItem.installation_scope == installation_scope)
    if version:
        conditions.append(SoftwareInventoryItem.version == version)
    grouped = select(
        SoftwareInventoryItem.product_key.label("software_key"),
        func.min(SoftwareInventoryItem.name).label("name"),
        func.min(SoftwareInventoryItem.publisher).label("publisher"),
        func.count().label("installation_count"),
        func.count(func.distinct(SoftwareInventoryItem.device_id)).label("device_count"),
        func.min(SoftwareInventoryItem.source).label("source"),
    ).where(*conditions).group_by(SoftwareInventoryItem.product_key)
    total = db.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    rows = db.execute(grouped.order_by(func.count().desc(), func.min(SoftwareInventoryItem.name))
                      .offset(offset).limit(limit)).all()
    return [{"software_key": row.software_key, "name": row.name, "publisher": row.publisher,
             "installation_count": row.installation_count, "device_count": row.device_count,
             "source": row.source} for row in rows], total


def software_summary(db: Session, stale_after_seconds: int = 604800) -> dict:
    present = SoftwareInventoryItem.is_present.is_(True)
    unique_count = db.scalar(select(func.count(func.distinct(SoftwareInventoryItem.product_key))).where(present)) or 0
    installation_count = db.scalar(select(func.count()).select_from(SoftwareInventoryItem).where(present)) or 0
    successful = select(SoftwareInventoryCollection.device_id,
            func.max(SoftwareInventoryCollection.completed_at).label("last_success")).where(
            SoftwareInventoryCollection.status.in_(("COMPLETE", "UNCHANGED", "PARTIAL"))
        ).group_by(SoftwareInventoryCollection.device_id).subquery()
    success_count = db.scalar(select(func.count()).select_from(successful)) or 0
    never_count = db.scalar(select(func.count()).select_from(Device).where(
        Device.enabled.is_(True), Device.enrollment_state == "APPROVED",
        ~Device.id.in_(select(successful.c.device_id)))) or 0
    stale_count = db.scalar(select(func.count()).select_from(successful).where(
        successful.c.last_success < now_utc() - timedelta(seconds=stale_after_seconds))) or 0
    latest_started = select(SoftwareInventoryCollection.device_id,
        func.max(SoftwareInventoryCollection.started_at).label("latest_started")).group_by(
            SoftwareInventoryCollection.device_id).subquery()
    latest_status = select(SoftwareInventoryCollection.device_id,
        SoftwareInventoryCollection.status).join(latest_started, and_(
            SoftwareInventoryCollection.device_id == latest_started.c.device_id,
            SoftwareInventoryCollection.started_at == latest_started.c.latest_started)).subquery()
    partial_count = db.scalar(select(func.count()).select_from(latest_status).where(
        latest_status.c.status == "PARTIAL")) or 0
    in_progress = db.scalar(select(func.count()).select_from(latest_status).where(
        latest_status.c.status == "IN_PROGRESS")) or 0
    common, _ = global_software_list(db, limit=5)
    return {"unique_applications": unique_count, "total_installations": installation_count,
            "devices_with_successful_inventory": success_count, "stale_devices": stale_count,
            "never_reported_devices": never_count, "partial_devices": partial_count, "collecting_devices": in_progress,
            "most_common": common}


def software_installations(db: Session, software_key: str, offset: int = 0, limit: int = 200) -> tuple[list[dict], int]:
    query = select(SoftwareInventoryItem, Device).join(Device, Device.id == SoftwareInventoryItem.device_id).where(
        SoftwareInventoryItem.product_key == software_key,
        SoftwareInventoryItem.is_present.is_(True))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(SoftwareInventoryItem.name, Device.assigned_name, Device.hostname)
                      .offset(offset).limit(limit)).all()
    return [{**_item_out(item), "device_name": device.assigned_name, "hostname": device.hostname}
            for item, device in rows], total
