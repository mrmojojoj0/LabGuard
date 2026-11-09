from __future__ import annotations

from datetime import UTC, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from labguard_server.models import Device, DeviceCredential, DeviceStatus, DeviceTelemetryLatest, TelemetrySample, now_utc
from labguard_server.schemas import TelemetrySnapshotIn


def record_telemetry(db: Session, device_id: UUID, sequence: int, payload: TelemetrySnapshotIn,
                     min_interval_seconds: float, retention_days: int):
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if status is None or device is None or credential is None or credential.revoked_at is not None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence <= status.last_sequence:
        return None, "replayed_sequence"

    now = now_utc()
    status.last_sequence = sequence
    latest = db.get(DeviceTelemetryLatest, device_id)
    if latest is not None and (now - _utc(latest.received_at)).total_seconds() < min_interval_seconds:
        db.commit()
        return None, "telemetry_rate_limited"
    if _utc(payload.collected_at) > now + timedelta(minutes=5):
        db.commit()
        return None, "collection_time_in_future"

    partitions = [item.model_dump(mode="json") for item in payload.storage_partitions]
    interfaces = [item.model_dump(mode="json") for item in payload.network_interfaces]
    cpu = payload.cpu
    memory = payload.memory
    os_info = payload.operating_system
    fields = {
        "collected_at": _utc(payload.collected_at), "received_at": now,
        "processor_name": cpu.processor_name, "logical_processors": cpu.logical_processors,
        "physical_cores": cpu.physical_cores, "cpu_percent": cpu.utilization_percent,
        "memory_total_bytes": memory.total_bytes, "memory_used_bytes": memory.used_bytes,
        "memory_available_bytes": memory.available_bytes, "memory_percent": memory.utilization_percent,
        "storage_partitions": partitions, "windows_edition": os_info.edition,
        "os_version": os_info.version, "build_number": os_info.build_number,
        "architecture": os_info.architecture, "hostname": os_info.hostname,
        "username": os_info.username, "agent_account": os_info.agent_account,
        "network_connections": ([item.model_dump(mode="json") for item in payload.network_connections]
                                if payload.network_connections is not None else None),
        "boot_time": _utc(payload.boot_time), "uptime_seconds": payload.uptime_seconds,
        "network_interfaces": interfaces,
    }
    if latest is None:
        latest = DeviceTelemetryLatest(device_id=device_id, **fields)
        db.add(latest)
    else:
        for name, value in fields.items():
            setattr(latest, name, value)

    disk_total = sum(item.total_bytes for item in payload.storage_partitions)
    disk_used = sum(item.used_bytes for item in payload.storage_partitions)
    db.add(TelemetrySample(
        device_id=device_id, collected_at=_utc(payload.collected_at), received_at=now,
        cpu_percent=cpu.utilization_percent, memory_used_bytes=memory.used_bytes,
        memory_total_bytes=memory.total_bytes, memory_percent=memory.utilization_percent,
        disk_used_bytes=disk_used, disk_total_bytes=disk_total,
        disk_percent=(disk_used / disk_total * 100) if disk_total else None,
    ))
    db.execute(delete(TelemetrySample).where(
        TelemetrySample.device_id == device_id,
        TelemetrySample.received_at < now - timedelta(days=retention_days),
    ))
    db.commit()
    return now, None


def consume_rejected_telemetry_sequence(db: Session, device_id: UUID, sequence: int) -> None:
    """Keep the shared event sequence monotonic after an invalid telemetry payload."""
    status = db.scalar(select(DeviceStatus).where(DeviceStatus.device_id == device_id).with_for_update())
    device = db.get(Device, device_id)
    credential = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device_id))
    if status is None or device is None or credential is None or credential.revoked_at is not None or not device.enabled or device.enrollment_state != "APPROVED":
        raise HTTPException(status_code=401, detail={"code": "device_unavailable", "message": "Device is no longer authorized"})
    if sequence > status.last_sequence:
        status.last_sequence = sequence
        db.commit()


def latest_telemetry(db: Session, device_id: UUID, stale_after_seconds: int):
    latest = db.get(DeviceTelemetryLatest, device_id)
    if latest is None:
        return {"device_id": str(device_id), "snapshot": None, "stale": True,
                "stale_after_seconds": stale_after_seconds}
    now = now_utc()
    received = _utc(latest.received_at)
    snapshot = {
        "collected_at": latest.collected_at.isoformat(), "received_at": latest.received_at.isoformat(),
        "cpu": {"processor_name": latest.processor_name, "logical_processors": latest.logical_processors,
                "physical_cores": latest.physical_cores, "utilization_percent": latest.cpu_percent},
        "memory": {"total_bytes": latest.memory_total_bytes, "used_bytes": latest.memory_used_bytes,
                   "available_bytes": latest.memory_available_bytes, "utilization_percent": latest.memory_percent},
        "storage_partitions": latest.storage_partitions,
        "operating_system": {"edition": latest.windows_edition, "version": latest.os_version,
                             "build_number": latest.build_number, "architecture": latest.architecture,
                             "hostname": latest.hostname, "username": latest.username,
                             "agent_account": latest.agent_account},
        "network_connections": latest.network_connections,
        "boot_time": latest.boot_time.isoformat(), "uptime_seconds": latest.uptime_seconds,
        "network_interfaces": latest.network_interfaces,
    }
    return {"device_id": str(device_id), "snapshot": snapshot,
            "stale": (now - received).total_seconds() > stale_after_seconds,
            "stale_after_seconds": stale_after_seconds}


def telemetry_history(db: Session, device_id: UUID, limit: int, retention_days: int):
    cutoff = now_utc() - timedelta(days=retention_days)
    rows = db.scalars(select(TelemetrySample).where(
        TelemetrySample.device_id == device_id, TelemetrySample.received_at >= cutoff,
    ).order_by(TelemetrySample.received_at.desc()).limit(limit)).all()
    return [{"collected_at": row.collected_at.isoformat(), "received_at": row.received_at.isoformat(),
             "cpu_percent": row.cpu_percent, "memory_percent": row.memory_percent,
             "memory_used_bytes": row.memory_used_bytes, "memory_total_bytes": row.memory_total_bytes,
             "disk_percent": row.disk_percent, "disk_used_bytes": row.disk_used_bytes,
             "disk_total_bytes": row.disk_total_bytes} for row in reversed(rows)]


def telemetry_summary(db: Session, stale_after_seconds: int):
    latest = db.scalars(select(DeviceTelemetryLatest)).all()
    now = now_utc()
    fresh = [row for row in latest if (now - _utc(row.received_at)).total_seconds() <= stale_after_seconds]
    count = len(fresh)
    return {"reporting_devices": count, "stale_devices": len(latest) - count,
            "average_cpu_percent": sum(row.cpu_percent for row in fresh) / count if count else None,
            "average_memory_percent": sum(row.memory_percent for row in fresh) / count if count else None,
            "average_disk_percent": _average_disk_percent(fresh)}


def _average_disk_percent(rows):
    totals = []
    for row in rows:
        total = sum(part.get("total_bytes", 0) for part in row.storage_partitions)
        used = sum(part.get("used_bytes", 0) for part in row.storage_partitions)
        if total:
            totals.append(used / total * 100)
    return sum(totals) / len(totals) if totals else None


def purge_expired_telemetry(db: Session, retention_days: int) -> int:
    result = db.execute(delete(TelemetrySample).where(
        TelemetrySample.received_at < now_utc() - timedelta(days=retention_days)))
    db.commit()
    return result.rowcount or 0


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
