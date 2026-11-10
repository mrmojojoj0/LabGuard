import asyncio
import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from labguard_server.models import DeviceProcessRequest, now_utc
from labguard_server.services import claim_device_ticket, record_agent_event
from labguard_server.schemas import TelemetrySnapshotIn
from labguard_server.telemetry import consume_rejected_telemetry_sequence, purge_expired_telemetry, record_telemetry
from labguard_server.schemas import SoftwareInventoryBatchIn
from labguard_server.software_inventory import record_software_inventory_batch
from labguard_server.schemas import SoftwareJobEventIn
from labguard_server.software_jobs import (dispatch_pending_software_jobs, record_software_job_event,
                                           software_job_allows_inventory)
from labguard_server.rdp_access import record_rdp_access_result
from labguard_server.schemas import RdpAccessResultIn
from labguard_server.process_management import record_process_result
from labguard_server.schemas import ProcessResultIn
from labguard_server.schemas import PeripheralSnapshotIn
from labguard_server.peripheral_activity import record_peripheral_snapshot
from labguard_server.schemas import ScreenshotChunkIn, ScreenshotCaptureFailedIn
from labguard_server.screenshot_service import receive_chunk, fail_capture
from labguard_server.schemas import WfpEventBatchIn
from labguard_server.wfp_activity import record_wfp_batch

router = APIRouter(prefix="/api/v1")
MAX_FRAME_BYTES = 64 * 1024


class ClientEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: str = Field(pattern=r"^labguard\.agent$")
    schema_version: int = Field(ge=1, le=1)
    event_id: UUID
    device_id: UUID
    sequence: int = Field(ge=1)
    sent_at: str = Field(min_length=20, max_length=40)
    type: str = Field(max_length=40)
    payload: dict


def _claim_ticket(websocket: WebSocket, token: str) -> UUID | None:
    factory = websocket.app.state.session_factory
    with factory() as db:
        return claim_device_ticket(db, token)


def _record(device_id: UUID, sequence: int, event_type: str, websocket: WebSocket, agent_version: str | None = None):
    with websocket.app.state.session_factory() as db:
        from labguard_server.models import DeviceStatus
        previous = db.get(DeviceStatus, device_id)
        previous_state = previous.agent_state if previous else None
        received_at = record_agent_event(db, device_id, sequence, event_type, agent_version)
        current = db.get(DeviceStatus, device_id)
        if current is not None and current.agent_state != previous_state:
            websocket.app.state.admin_events.publish({"type": "device.status", "device_id": str(device_id),
                "agent_state": current.agent_state, "changed_at": current.changed_at.isoformat()})
        return received_at


def _persist_telemetry(factory, device_id, sequence, payload, minimum_interval, retention_days):
    with factory() as db:
        return record_telemetry(db, device_id, sequence, payload, minimum_interval, retention_days)


def _persist_software_inventory(factory, device_id, sequence, payload, cooldown, retention_days,
                                manual_refresh_authorized=False, job_refresh_authorized=False):
    with factory() as db:
        return record_software_inventory_batch(db, device_id, sequence, payload, cooldown,
                                               retention_days, manual_refresh_authorized,
                                               job_refresh_authorized)


def _software_job_allows_inventory(factory, device_id, job_id):
    with factory() as db:
        return software_job_allows_inventory(db, device_id, job_id)


def _persist_software_job_event(factory, device_id, sequence, event_type, payload):
    with factory() as db:
        return record_software_job_event(db, device_id, sequence, event_type, payload)


def _persist_rdp_result(factory, device_id, sequence, payload):
    with factory() as db:
        return record_rdp_access_result(db, device_id, sequence, payload)


def _persist_process_result(factory, device_id, sequence, payload):
    with factory() as db:
        return record_process_result(db, device_id, sequence, payload)


def _persist_peripheral_snapshot(factory, device_id, sequence, payload):
    with factory() as db:
        return record_peripheral_snapshot(db, device_id, sequence, payload)


def _persist_wfp_batch(factory, device_id, sequence, payload):
    with factory() as db:
        return record_wfp_batch(db, device_id, sequence, payload)


def _persist_screenshot_event(factory, settings, device_id, sequence, event_type, payload):
    with factory() as db:
        record_agent_event(db, device_id, sequence, event_type)
        if event_type == "client.screenshot.chunk":
            return receive_chunk(db, settings, device_id, payload)
        return fail_capture(db, device_id, payload.capture_id, payload.error_code)


def _consume_invalid_telemetry(factory, device_id, sequence):
    with factory() as db:
        consume_rejected_telemetry_sequence(db, device_id, sequence)


def _parse(text: str) -> ClientEnvelope:
    if len(text.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ValueError("frame_too_large")
    try:
        value = json.loads(text)
        return ClientEnvelope.model_validate(value)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("invalid_frame") from exc


async def _receive(websocket: WebSocket) -> ClientEnvelope:
    raw = await websocket.receive_text()
    return _parse(raw)


async def _send(websocket: WebSocket, device_id: UUID, event_type: str, payload: dict):
    message = {"protocol": "labguard.agent", "schema_version": 1, "event_id": str(uuid4()),
               "device_id": str(device_id), "sequence": 0, "sent_at": now_utc().isoformat(),
               "type": event_type, "payload": payload}
    lock = websocket.app.state.active_device_send_locks.get(device_id)
    if lock is None:
        await websocket.send_json(message)
    else:
        async with lock:
            await websocket.send_json(message)


async def request_software_inventory_refresh(application, device_id: UUID, request_id: UUID) -> bool:
    websocket = application.state.active_devices.get(device_id)
    if websocket is None:
        return False
    try:
        await _send(websocket, device_id, "server.software_inventory.refresh", {"request_id": str(request_id)})
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


async def send_software_job_offer(application, device_id: UUID, payload: dict) -> bool:
    websocket = application.state.active_devices.get(device_id)
    if websocket is None:
        return False
    try:
        await _send(websocket, device_id, "server.software_job.offer", payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


async def send_rdp_access_request(application, device_id: UUID, payload: dict) -> bool:
    websocket = application.state.active_devices.get(device_id)
    if websocket is None:
        return False
    try:
        await _send(websocket, device_id, "server.rdp.access.request", payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


async def send_process_request(application, device_id: UUID, payload: dict) -> bool:
    websocket = application.state.active_devices.get(device_id)
    if websocket is None:
        return False
    try:
        await _send(websocket, device_id, "server.process.request", payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


async def dispatch_pending_process_requests(application, device_id: UUID) -> None:
    with application.state.session_factory() as db:
        now = now_utc()
        pending = db.query(DeviceProcessRequest).filter(
            DeviceProcessRequest.device_id == device_id,
            DeviceProcessRequest.status == "PENDING",
            DeviceProcessRequest.expires_at > now,
        ).order_by(DeviceProcessRequest.created_at).all()
        items = [{"request_id": str(row.id), "operation": row.operation,
                  "target_pid": row.target_pid,
                  "target_created_at_us": row.target_created_at_us,
                  "expires_at": row.expires_at.isoformat()} for row in pending]
    for payload in items:
        if not await send_process_request(application, device_id, payload):
            break


async def send_screenshot_request(application, device_id: UUID, payload: dict) -> bool:
    websocket = application.state.active_devices.get(device_id)
    if websocket is None:
        return False
    try:
        await _send(websocket, device_id, "server.screenshot.request", payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


@router.websocket("/agent/session")
async def agent_session(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    device_id = _claim_ticket(websocket, token) if token else None
    if device_id is None:
        await websocket.close(code=4401, reason="invalid_or_expired_ticket")
        return
    await websocket.accept()
    active = websocket.app.state.active_devices
    previous = active.get(device_id)
    if previous is not None:
        try:
            await previous.close(code=4001, reason="connection_replaced")
        except RuntimeError:
            pass
    active[device_id] = websocket
    websocket.app.state.active_device_send_locks[device_id] = asyncio.Lock()
    websocket.app.state.admin_events.publish({"type": "device.connection", "device_id": str(device_id), "connected": True})
    try:
        try:
            hello = await asyncio.wait_for(_receive(websocket), timeout=10)
        except (asyncio.TimeoutError, ValueError):
            await websocket.close(code=4400, reason="hello_required")
            return
        if hello.device_id != device_id or hello.type != "client.hello":
            await websocket.close(code=4401, reason="invalid_hello")
            return
        if not isinstance(hello.payload.get("agent_version"), str) or not isinstance(hello.payload.get("boot_id"), str):
            await websocket.close(code=4400, reason="invalid_hello_payload")
            return
        try:
            _record(device_id, hello.sequence, "client.hello", websocket, hello.payload["agent_version"])
        except HTTPException:
            await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
            return
        except Exception:
            logging.getLogger("labguard_server.websocket").exception("Failed recording device hello")
            await websocket.close(code=1011, reason="server_error")
            return
        settings = websocket.app.state.settings
        await _send(websocket, device_id, "server.welcome", {"server_time": now_utc().isoformat(),
                    "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
                    "delayed_after_seconds": settings.delayed_after_seconds,
                    "offline_after_seconds": settings.offline_after_seconds, "protocol_version": 1})
        await _send(websocket, device_id, "server.ack", {"event_type": "client.hello", "accepted": True, "server_time": now_utc().isoformat()})
        await dispatch_pending_software_jobs(websocket.app, device_id)
        await dispatch_pending_process_requests(websocket.app, device_id)

        while True:
            raw = await websocket.receive_text()
            try:
                event = _parse(raw)
            except ValueError:
                await websocket.close(code=4400, reason="invalid_or_oversized_frame")
                return
            if event.device_id != device_id:
                await websocket.close(code=4401, reason="authenticated_device_mismatch")
                return
            if event.type not in {"client.heartbeat", "client.telemetry", "client.software_inventory",
                                  "client.job.accepted", "client.job.started", "client.job.progress",
                                  "client.job.completed", "client.job.failed", "client.rdp.access.result",
                                  "client.process.result", "client.peripheral.snapshot",
                                  "client.network.wfp", "client.screenshot.chunk", "client.screenshot.failed"}:
                await websocket.close(code=4400, reason="unsupported_event")
                return
            if event.type == "client.telemetry":
                try:
                    payload = TelemetrySnapshotIn.model_validate(event.payload)
                except ValidationError:
                    try:
                        await asyncio.to_thread(_consume_invalid_telemetry, websocket.app.state.session_factory,
                                                device_id, event.sequence)
                    except HTTPException:
                        await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                        return
                    await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                        "accepted": False, "reason": "invalid_telemetry"})
                    continue
                try:
                    received_at, reason = await asyncio.to_thread(_persist_telemetry,
                        websocket.app.state.session_factory, device_id, event.sequence, payload,
                        websocket.app.state.settings.telemetry_min_interval_seconds,
                        websocket.app.state.settings.telemetry_retention_days)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing device telemetry")
                    await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                        "accepted": False, "reason": "telemetry_storage_error"})
                    continue
                accepted = received_at is not None
                if accepted:
                    websocket.app.state.admin_events.publish({"type": "device.telemetry",
                        "device_id": str(device_id), "received_at": received_at.isoformat()})
                await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                    "accepted": accepted, "server_received_at": received_at.isoformat() if accepted else None,
                    "reason": reason})
                continue
            if event.type == "client.peripheral.snapshot":
                try:
                    snapshot = PeripheralSnapshotIn.model_validate(event.payload)
                except ValidationError:
                    try:
                        await asyncio.to_thread(_consume_invalid_telemetry, websocket.app.state.session_factory,
                                                device_id, event.sequence)
                    except HTTPException:
                        await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                        return
                    await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                        "accepted": False, "reason": "invalid_peripheral_snapshot"})
                    continue
                try:
                    received_at, changed, reason = await asyncio.to_thread(
                        _persist_peripheral_snapshot, websocket.app.state.session_factory,
                        device_id, event.sequence, snapshot)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception(
                        "Failed storing peripheral snapshot")
                    received_at, changed, reason = None, 0, "peripheral_storage_error"
                accepted = received_at is not None
                if accepted:
                    websocket.app.state.admin_events.publish({"type": "device.peripherals",
                        "device_id": str(device_id), "changed": changed,
                        "received_at": received_at.isoformat()})
                await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                    "accepted": accepted, "changed": changed,
                    "server_received_at": received_at.isoformat() if accepted else None,
                    "reason": reason})
                continue
            if event.type == "client.network.wfp":
                try:
                    batch = WfpEventBatchIn.model_validate(event.payload)
                except ValidationError:
                    try:
                        await asyncio.to_thread(_consume_invalid_telemetry, websocket.app.state.session_factory,
                                                device_id, event.sequence)
                    except HTTPException:
                        await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                        return
                    await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                        "accepted": False, "reason": "invalid_wfp_batch"})
                    continue
                try:
                    accepted, result = await asyncio.to_thread(_persist_wfp_batch,
                        websocket.app.state.session_factory, device_id, event.sequence, batch)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing WFP events")
                    accepted, result = False, "wfp_storage_error"
                if accepted:
                    websocket.app.state.admin_events.publish({"type": "device.network", "device_id": str(device_id)})
                await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                    "accepted": accepted, "result": result if accepted else None,
                    "reason": None if accepted else result})
                continue
            if event.type == "client.software_inventory":
                try:
                    inventory = SoftwareInventoryBatchIn.model_validate(event.payload)
                except ValidationError:
                    await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id),
                        "accepted": False, "reason": "invalid_software_inventory"})
                    continue
                manual_refresh_authorized = False
                if inventory.request_id is not None:
                    pending_refresh = websocket.app.state.software_refresh_requests.get(device_id)
                    if (pending_refresh is None
                            or pending_refresh["request_id"] != str(inventory.request_id)):
                        await _send(websocket, device_id, "server.ack", {
                            "event_id": str(event.event_id), "accepted": False,
                            "reason": "invalid_refresh_request"})
                        continue
                    manual_refresh_authorized = True
                job_refresh_authorized = False
                if inventory.job_id is not None:
                    job_refresh_authorized = await asyncio.to_thread(
                        _software_job_allows_inventory, websocket.app.state.session_factory,
                        device_id, inventory.job_id)
                    if not job_refresh_authorized:
                        await _send(websocket, device_id, "server.ack", {
                            "event_id": str(event.event_id), "accepted": False,
                            "reason": "invalid_job_inventory_request"})
                        continue
                try:
                    result, completed = await asyncio.to_thread(_persist_software_inventory,
                        websocket.app.state.session_factory, device_id, event.sequence, inventory,
                        websocket.app.state.settings.software_inventory_min_interval_seconds,
                        websocket.app.state.settings.software_inventory_retention_days,
                        manual_refresh_authorized, job_refresh_authorized)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing software inventory")
                    result, completed = {"accepted": False, "reason": "inventory_storage_error"}, False
                if completed:
                    if inventory.request_id is not None:
                        pending_refresh = websocket.app.state.software_refresh_requests.get(device_id)
                        if pending_refresh and pending_refresh["request_id"] == str(inventory.request_id):
                            websocket.app.state.software_refresh_requests.pop(device_id, None)
                    websocket.app.state.admin_events.publish({"type": "software.inventory",
                        "device_id": str(device_id), "status": result.get("status"),
                        "completed_at": now_utc().isoformat()})
                await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id), **result})
                continue
            if event.type.startswith("client.job."):
                try:
                    job_event = SoftwareJobEventIn.model_validate(event.payload)
                except ValidationError:
                    await _send(websocket, device_id, "server.ack", {
                        "event_id": str(event.event_id), "accepted": False, "reason": "invalid_job_event"})
                    continue
                try:
                    result, terminal = await asyncio.to_thread(
                        _persist_software_job_event, websocket.app.state.session_factory,
                        device_id, event.sequence, event.type, job_event)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing software job event")
                    result, terminal = {"accepted": False, "reason": "job_storage_error"}, False
                if result.get("accepted"):
                    websocket.app.state.admin_events.publish({"type": "software.job",
                        "job_id": str(job_event.job_id), "device_id": str(device_id),
                        "status": result.get("status")})
                await _send(websocket, device_id, "server.ack", {
                    "event_id": str(event.event_id), **result})
                continue
            if event.type == "client.rdp.access.result":
                try:
                    rdp_result = RdpAccessResultIn.model_validate(event.payload)
                except ValidationError:
                    await _send(websocket, device_id, "server.ack", {
                        "event_id": str(event.event_id), "accepted": False,
                        "reason": "invalid_rdp_access_result"})
                    continue
                try:
                    result = await asyncio.to_thread(_persist_rdp_result,
                        websocket.app.state.session_factory, device_id, event.sequence, rdp_result)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing RDP access result")
                    result = {"accepted": False, "reason": "rdp_access_storage_error"}
                if result.get("accepted"):
                    websocket.app.state.admin_events.publish({"type": "rdp.access",
                        "request_id": result["request_id"], "device_id": str(device_id),
                        "status": result["status"]})
                await _send(websocket, device_id, "server.ack", {
                    "event_id": str(event.event_id), **result})
                continue
            if event.type == "client.process.result":
                try:
                    process_result = ProcessResultIn.model_validate(event.payload)
                except ValidationError:
                    await _send(websocket, device_id, "server.ack", {
                        "event_id": str(event.event_id), "accepted": False,
                        "reason": "invalid_process_result"})
                    continue
                try:
                    result = await asyncio.to_thread(_persist_process_result,
                        websocket.app.state.session_factory, device_id, event.sequence, process_result)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing process operation result")
                    result = {"accepted": False, "reason": "process_result_storage_error"}
                if result.get("accepted"):
                    websocket.app.state.admin_events.publish({"type": "device.process", "device_id": str(device_id),
                        "request_id": str(process_result.request_id), "status": result.get("status")})
                await _send(websocket, device_id, "server.ack", {
                    "event_id": str(event.event_id), **result})
                continue
            if event.type in {"client.screenshot.chunk", "client.screenshot.failed"}:
                try:
                    screenshot_payload = (ScreenshotChunkIn.model_validate(event.payload)
                        if event.type == "client.screenshot.chunk"
                        else ScreenshotCaptureFailedIn.model_validate(event.payload))
                except ValidationError:
                    await _send(websocket, device_id, "server.ack", {
                        "event_id": str(event.event_id), "accepted": False,
                        "reason": "invalid_screenshot_event"})
                    continue
                try:
                    result = await asyncio.to_thread(_persist_screenshot_event,
                        websocket.app.state.session_factory, websocket.app.state.settings,
                        device_id, event.sequence, event.type, screenshot_payload)
                except HTTPException:
                    await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                    return
                except Exception:
                    logging.getLogger("labguard_server.websocket").exception("Failed storing screenshot capture")
                    result = {"accepted": False, "reason": "screenshot_storage_error"}
                if result.get("accepted") and result.get("status") in {"READY", "FAILED"}:
                    websocket.app.state.admin_events.publish({"type": "device.screenshot",
                        "capture_id": str(screenshot_payload.capture_id), "device_id": str(device_id),
                        "status": result["status"]})
                await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id), **result})
                continue
            try:
                received_at = _record(device_id, event.sequence, "client.heartbeat", websocket)
            except HTTPException:
                await websocket.close(code=4401, reason="device_not_authorized_or_replayed")
                return
            except Exception:
                logging.getLogger("labguard_server.websocket").exception("Failed recording device heartbeat")
                await websocket.close(code=1011, reason="server_error")
                return
            await _send(websocket, device_id, "server.ack", {"event_id": str(event.event_id), "accepted": True,
                        "server_received_at": received_at.isoformat()})
    except WebSocketDisconnect:
        return
    finally:
        if active.get(device_id) is websocket:
            active.pop(device_id, None)
            websocket.app.state.active_device_send_locks.pop(device_id, None)
            websocket.app.state.admin_events.publish({"type": "device.connection", "device_id": str(device_id), "connected": False})


async def status_monitor(application):
    settings = application.state.settings
    period = min(max(settings.heartbeat_interval_seconds / 2, 0.1), 1.0)
    while True:
        await asyncio.sleep(period)
        with application.state.session_factory() as db:  # type: Session
            db.expire_all()
            from labguard_server.services import refresh_device_states
            def emit_change(device_id, previous, desired, changed_at):
                application.state.admin_events.publish({"type": "device.status", "device_id": str(device_id),
                    "previous_state": previous, "agent_state": desired, "changed_at": changed_at.isoformat()})
            refresh_device_states(db, settings.delayed_after_seconds, settings.offline_after_seconds, emit_change)


async def telemetry_retention_monitor(application):
    settings = application.state.settings
    while True:
        try:
            def purge():
                with application.state.session_factory() as db:
                    purge_expired_telemetry(db, settings.telemetry_retention_days)
            await asyncio.to_thread(purge)
        except Exception:
            logging.getLogger("labguard_server.telemetry").exception("Telemetry retention cleanup failed")
        await asyncio.sleep(3600)
