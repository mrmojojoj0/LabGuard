"""Room-scoped RTSP sampling and privacy-preserving object detection."""
import asyncio
import base64
import hashlib
import logging
import threading
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from labguard_server.models import LabCamera, LabCameraDetection, Room, now_utc

logger = logging.getLogger("labguard_server.cameras")

# COCO dataset category IDs used by the ONNX Model Zoo SSD-MobileNetV1 weights.
TARGET_CLASSES = {
    44: "bottle", 47: "cup", 51: "bowl", 52: "banana", 53: "apple",
    54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot",
    58: "hot dog", 59: "pizza", 60: "donut", 61: "cake",
}
_model = None
_model_lock = threading.Lock()


def _fernet(application) -> Fernet:
    secret = application.state.settings.camera_encryption_key
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail={"code": "camera_encryption_unconfigured",
            "message": "Set CAMERA_ENCRYPTION_KEY (at least 32 characters) before configuring cameras."})
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_uri(application, uri: str) -> str:
    return _fernet(application).encrypt(uri.encode("utf-8")).decode("ascii")


def _decrypt_uri(application, value: str) -> str:
    try:
        return _fernet(application).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise RuntimeError("camera_secret_unavailable") from exc


def camera_out(db: Session, camera: LabCamera) -> dict:
    room = db.get(Room, camera.room_id)
    return {"id": camera.id, "room_id": camera.room_id, "room_name": room.name if room else "Unknown lab",
        "name": camera.name, "enabled": camera.enabled, "state": camera.state,
        "error_code": camera.error_code, "last_frame_at": camera.last_frame_at, "stream_configured": True}


def create_camera(db: Session, application, room_id: UUID, name: str, stream_uri: str) -> dict:
    if db.get(Room, room_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Lab not found"})
    total = db.scalar(select(func.count(LabCamera.id))) or 0
    in_room = db.scalar(select(func.count(LabCamera.id)).where(LabCamera.room_id == room_id)) or 0
    if total >= 32 or in_room >= 8:
        raise HTTPException(status_code=409, detail={"code": "camera_capacity_reached",
            "message": "LabGuard supports up to 8 cameras per lab and 32 cameras total."})
    row = LabCamera(room_id=room_id, name=name.strip(), stream_uri_encrypted=_encrypt_uri(application, stream_uri),
        enabled=True, state="WAITING")
    db.add(row)
    db.flush()
    return camera_out(db, row)


def list_cameras(db: Session, room_id: UUID | None = None) -> list[dict]:
    query = select(LabCamera).order_by(LabCamera.room_id, LabCamera.name)
    if room_id is not None:
        query = query.where(LabCamera.room_id == room_id)
    return [camera_out(db, row) for row in db.scalars(query).all()]


def update_camera(db: Session, application, row: LabCamera, changes: dict) -> dict:
    if "name" in changes and changes["name"] is not None:
        row.name = changes["name"].strip()
    if "stream_uri" in changes and changes["stream_uri"] is not None:
        row.stream_uri_encrypted = _encrypt_uri(application, changes["stream_uri"])
        row.state, row.error_code = "WAITING", None
    if "enabled" in changes and changes["enabled"] is not None:
        row.enabled = changes["enabled"]
        if not row.enabled:
            row.state, row.error_code = "DISABLED", None
            application.state.camera_frames.pop(row.id, None)
        else:
            row.state, row.error_code = "WAITING", None
    db.flush()
    return camera_out(db, row)


def delete_camera(db: Session, row: LabCamera) -> None:
    db.delete(row)


def list_detections(db: Session, room_id: UUID | None = None, camera_id: UUID | None = None,
                    limit: int = 100) -> list[dict]:
    query = select(LabCameraDetection, LabCamera, Room).join(LabCamera, LabCamera.id == LabCameraDetection.camera_id) \
        .join(Room, Room.id == LabCameraDetection.room_id).order_by(LabCameraDetection.occurred_at.desc())
    if room_id is not None:
        query = query.where(LabCameraDetection.room_id == room_id)
    if camera_id is not None:
        query = query.where(LabCameraDetection.camera_id == camera_id)
    return [{"id": event.id, "camera_id": camera.id, "room_id": room.id, "camera_name": camera.name,
        "room_name": room.name, "label": event.label, "count": event.count, "confidence": event.confidence,
        "occurred_at": event.occurred_at} for event, camera, room in db.execute(query.limit(limit)).all()]


def _detect_frame(application, encrypted_uri: str) -> tuple[list[tuple[str, int, float]], bytes]:
    """Open one RTSP sample, infer on it, and release the frame without writing it to disk."""
    model_path = Path(application.state.settings.camera_detection_model)
    if not model_path.is_absolute():
        working_directory_path = Path.cwd() / model_path
        server_directory_path = Path(__file__).resolve().parents[2] / model_path
        model_path = working_directory_path if working_directory_path.is_file() else server_directory_path
    if not model_path.is_file():
        raise RuntimeError("camera_model_missing")

    import cv2
    import numpy as np
    import onnxruntime as ort

    uri = _decrypt_uri(application, encrypted_uri)
    source = cv2.VideoCapture(uri, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000])
    try:
        if not source.isOpened():
            raise RuntimeError("camera_stream_unavailable")
        ok, frame = source.read()
        if not ok or frame is None:
            raise RuntimeError("camera_frame_unavailable")
    finally:
        source.release()

    global _model
    with _model_lock:
        if _model is None:
            _model = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_meta = _model.get_inputs()[0]
    input_image = cv2.cvtColor(cv2.resize(frame, (300, 300)), cv2.COLOR_BGR2RGB)[None, ...].astype(np.uint8)
    output_names = [output.name for output in _model.get_outputs()]
    if not {"detection_boxes", "detection_classes", "detection_scores", "num_detections"}.issubset(output_names):
        raise RuntimeError("camera_model_output_invalid")
    output_values = _model.run(output_names, {input_meta.name: input_image})
    outputs = dict(zip(output_names, output_values))
    num = outputs["num_detections"]
    boxes = outputs["detection_boxes"]
    scores = outputs["detection_scores"]
    class_ids = outputs["detection_classes"]
    detected: dict[str, tuple[int, float]] = {}
    box_rows = boxes.reshape(-1, 4)
    for index in range(min(int(num.reshape(-1)[0]), len(scores.reshape(-1)))):
        label = TARGET_CLASSES.get(int(class_ids.reshape(-1)[index]))
        score = float(scores.reshape(-1)[index])
        if label and score >= 0.40:
            count, previous_confidence = detected.get(label, (0, 0.0))
            detected[label] = (count + 1, max(previous_confidence, score))
            top, left, bottom, right = box_rows[index]
            x1, y1 = max(0, int(left * frame.shape[1])), max(0, int(top * frame.shape[0]))
            x2, y2 = min(frame.shape[1] - 1, int(right * frame.shape[1])), min(frame.shape[0] - 1, int(bottom * frame.shape[0]))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 210, 80), 2)
            cv2.putText(frame, f"{label} {score:.0%}", (x1, max(16, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 210, 80), 2, cv2.LINE_AA)
    detection_rows = [(label, count, confidence) for label, (count, confidence) in sorted(detected.items())]
    scale = min(640 / frame.shape[1], 480 / frame.shape[0], 1.0)
    preview_size = (max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale)))
    ok, encoded = cv2.imencode(".jpg", cv2.resize(frame, preview_size), [cv2.IMWRITE_JPEG_QUALITY, 50])
    if not ok:
        raise RuntimeError("camera_preview_encode_failed")
    return detection_rows, encoded.tobytes()


def _sample_camera(application, camera_id: UUID) -> None:
    factory = application.state.session_factory
    db: Session = factory()
    try:
        camera = db.get(LabCamera, camera_id)
        if camera is None:
            return
        if not camera.enabled:
            camera.state = "DISABLED"
            application.state.camera_frames.pop(camera.id, None)
            db.commit()
            return
        try:
            detections, preview = _detect_frame(application, camera.stream_uri_encrypted)
        except Exception as exc:
            if isinstance(exc, ImportError):
                code = "camera_dependencies_unavailable"
            else:
                code = str(exc) if str(exc).startswith("camera_") else "camera_sample_failed"
            camera.state, camera.error_code = "ERROR", code
            application.state.camera_frames.pop(camera.id, None)
            db.commit()
            return
        now = now_utc()
        camera.state, camera.error_code, camera.last_frame_at = "ONLINE", None, now
        application.state.camera_frames[camera.id] = (now, preview)
        for label, count, confidence in detections:
            prior = db.scalar(select(LabCameraDetection).where(
                LabCameraDetection.camera_id == camera.id, LabCameraDetection.label == label,
                LabCameraDetection.occurred_at >= now - timedelta(minutes=1))
                .order_by(LabCameraDetection.occurred_at.desc()).limit(1))
            if prior:
                prior.count, prior.confidence, prior.occurred_at = count, confidence, now
            else:
                db.add(LabCameraDetection(camera_id=camera.id, room_id=camera.room_id,
                    label=label, count=count, confidence=confidence, occurred_at=now))
        db.execute(delete(LabCameraDetection).where(
            LabCameraDetection.occurred_at < now - timedelta(days=application.state.settings.camera_event_retention_days)))
        db.commit()
        if detections:
            application.state.admin_events.publish({"type": "camera.detection", "camera_id": str(camera_id),
                "room_id": str(camera.room_id), "occurred_at": now.isoformat()})
    except Exception:
        db.rollback()
        logger.exception("Camera sample persistence failed")
    finally:
        db.close()


async def lab_camera_monitor(application) -> None:
    tasks: dict[UUID, asyncio.Task] = {}
    while True:
        try:
            with application.state.session_factory() as db:
                camera_ids = set(db.scalars(select(LabCamera.id).where(LabCamera.enabled.is_(True))).all())
            for camera_id in camera_ids:
                if camera_id not in tasks or tasks[camera_id].done():
                    tasks[camera_id] = asyncio.create_task(_camera_loop(application, camera_id))
            for camera_id in list(tasks):
                if camera_id not in camera_ids:
                    tasks.pop(camera_id).cancel()
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            raise
        except Exception:
            logger.exception("Camera monitor reconciliation failed")
            await asyncio.sleep(5)


async def _camera_loop(application, camera_id: UUID) -> None:
    interval = application.state.settings.camera_sample_interval_seconds
    while True:
        await asyncio.to_thread(_sample_camera, application, camera_id)
        await asyncio.sleep(interval)
