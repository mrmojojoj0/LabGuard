# Lab Camera Monitoring

## Feature boundary

Lab camera monitoring is a separate server-managed feature from endpoint screenshots. Camera records represent configured camera sources and detection evidence; endpoint screenshot capture is a read-only client helper feature. Camera evidence must use its own authorization and retention lifecycle.

## Configuration and sampling pipeline

1. A LAB_ADMIN creates a camera under a room with a name and RTSP stream URI. The server enforces a maximum of 8 cameras per room and 32 total. It encrypts the URI with Fernet using the configured `CAMERA_ENCRYPTION_KEY`; API output reports that a stream is configured without returning its secret.
2. A same-process monitor reconciles enabled camera IDs and starts one asynchronous sampling loop per camera. Each loop samples at the configured interval. Sampling and image inference run in worker threads so they do not block the API event loop.
3. The sampler decrypts the URI in memory, opens one RTSP frame with bounded open/read timeouts, and releases the capture handle. It loads the configured ONNX model once under a process lock and runs CPU inference on a 300×300 resized frame.
4. The detector accepts a fixed set of COCO object classes (food/drink items) at confidence >= 0.40. It aggregates counts and maximum confidence by label, draws boxes on a reduced JPEG preview, and does not save every raw frame.
5. The latest preview and timestamp live in an in-memory per-camera frame map for the frame endpoint. Camera state and last-frame time are persisted. Stream/model/dependency/storage failures update an explicit ERROR code and clear the current preview.
6. When objects are detected, the service stores a preview evidence image. It reuses a recent image for detections within a one-minute window to limit file churn. Detection rows are similarly coalesced per camera and label within one minute by updating count, confidence and occurrence time; otherwise a new row is added.
7. Detection writes and retention cleanup commit to the database. A detection SSE invalidation prompts the dashboard to refetch canonical camera and detection state.

Detection rows can be queried by room and camera. The latest frame API serves an in-memory preview, while a separate evidence endpoint serves retained detection images. Camera list/detail output never exposes the RTSP URI. Mutations and evidence retrieval are role-protected; configuration/deletion changes are audited. Deleting a camera clears its in-memory frame and its evidence files before removing the record. Deleting an individual detection only removes its image when no remaining detection references it.

## Persistence, retention and security

Camera configuration and detections are database records; JPEG evidence is file-backed. Evidence roots have restrictive filesystem permissions (Windows ACLs or POSIX mode 0700), and stored filenames are generated from camera UUID and timestamp. Resolved file paths are checked to remain directly inside the configured root. Camera evidence expires after 24 hours; a periodic cleanup removes expired JPEGs and abandoned partial files. Detection metadata retention is independently configurable. Deletion and bulk-clear paths clean up unreferenced evidence.

Camera URI encryption depends on a stable, securely configured encryption key. Losing/changing that key makes stored URIs unreadable. Model weights and OpenCV/ONNX dependencies must be available to the server. The ONNX model is CPU-only in this implementation. In-memory previews and the sampler registry are process-local, so process restart drops the current frame and multi-worker deployments could sample the same camera more than once.

## Source map

Core implementation is `camera_monitoring.py`; API routes are in `api.py`; settings and lifecycle startup are in `config.py` and `main.py`. Models/migrations `0019_lab_camera_monitoring` and `0020_camera_detection_evidence` store camera and detection metadata. The dashboard uses `src/features/cameras` APIs. Live RTSP compatibility, model accuracy, load capacity and privacy/retention policy should be verified for the deployment environment.
