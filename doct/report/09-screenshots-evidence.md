# Screenshots and Evidence

## Purpose and constraints

Screenshot capture is an on-demand, read-only evidence feature. The Windows service runs in Session 0 and cannot capture the interactive desktop directly, so an authorized capture uses a narrowly scoped helper in the active console session. The helper captures pixels only: it must not show UI, automate input, or perform unrelated user-session work.

## Manual capture pipeline

1. A LAB_ADMIN submits a CSRF-protected capture request for an eligible online device.
2. The server creates durable capture metadata with request expiry and sends a typed capture request over the authenticated device socket.
3. The client validates request ID/expiry and starts the authorized active-console screenshot helper. If there is no active compatible console session, capture fails explicitly.
4. The helper returns an image payload to the service. The client sends the result over the same authenticated channel.
5. Server validates request/device association and size/type bounds, stores metadata and image bytes through the screenshot service, and reports the persisted capture to the dashboard.
6. Capture records expire under the configured 24-hour retention; authorized manual deletion removes evidence and metadata.

## Exam burst pipeline

When an exam violation is detected and screenshot-on-violation is enabled, the server queues four capture records: immediately and at +10, +20 and +30 seconds. A server-side dispatcher sends due requests to connected agents. Missing schedules and disconnected endpoints are marked failed. Screenshot failure does not roll back the violation record; they are separate evidence outcomes.

## Storage, privacy and limitations

Screenshots can consume material storage, especially where a violation creates four captures. Expiration and manual deletion are explicit lifecycle controls. Offline agents cannot be captured retroactively after a due request expires. The helper relies on an active console session and Windows deployment behavior; service/session behavior must be verified on the target OS. A screenshot is evidence of a screen at a moment, not proof of policy compliance or user identity.

## Source map

Server records, expiry, listing and deletion are in `screenshot_service.py`; dispatch is in `websocket.py` and the server monitor; endpoint request handling is in `agent.py`; capture adapters/helper are `screenshot_capture.py` and `screenshot_helper.py`. Screenshot metadata and exam burst migrations are under `labguard-server/migrations/versions`.
