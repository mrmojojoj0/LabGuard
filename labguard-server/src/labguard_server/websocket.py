import asyncio
import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from labguard_server.models import now_utc
from labguard_server.services import claim_device_ticket, record_agent_event

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
        return record_agent_event(db, device_id, sequence, event_type, agent_version)


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
    await websocket.send_json({"protocol": "labguard.agent", "schema_version": 1, "event_id": str(uuid4()),
                               "device_id": str(device_id), "sequence": 0, "sent_at": now_utc().isoformat(),
                               "type": event_type, "payload": payload})


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

        while True:
            raw = await websocket.receive_text()
            try:
                event = _parse(raw)
            except ValueError:
                await websocket.close(code=4400, reason="invalid_or_oversized_frame")
                return
            if event.device_id != device_id or event.type != "client.heartbeat":
                await websocket.close(code=4400, reason="unsupported_event")
                return
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


async def status_monitor(application):
    settings = application.state.settings
    period = min(max(settings.heartbeat_interval_seconds / 2, 0.1), 1.0)
    while True:
        await asyncio.sleep(period)
        with application.state.session_factory() as db:  # type: Session
            db.expire_all()
            from labguard_server.services import refresh_device_states
            refresh_device_states(db, settings.delayed_after_seconds, settings.offline_after_seconds)
