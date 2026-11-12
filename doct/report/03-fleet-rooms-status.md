# Fleet, Rooms, Status, and Live Dashboard Updates

## Feature model

The fleet view combines durable device identity and assignment with current connection health. A `Device` represents an enrolled endpoint; a separate `DeviceStatus` tracks agent and network state, heartbeat time, and state-change time. Room placement uses a `Room` and `DevicePosition` records with row/column coordinates. Keeping status separate from device inventory prevents an unreachable endpoint from being confused with a deleted or unknown endpoint.

## Room and layout pipeline

1. An authorized administrator creates or edits a room and its grid dimensions.
2. The dashboard submits a complete layout through a typed API request.
3. The server validates referenced devices, bounds and coordinate uniqueness, then saves the layout atomically so a partial drag/drop operation cannot leave inconsistent positions.
4. Device assignment and status are returned through REST. The dashboard renders the room grid and refreshes its authoritative data after an SSE invalidation.

Exam targeting reuses room assignment: at exam creation the server resolves the room's current approved target devices and persists the target set. The exam report's grid coordinates are calculated from current positions, so moving devices later can affect the layout shown in a historical report.

## State and liveness algorithm

An authenticated agent heartbeat updates server receipt time and device state. Liveness is based on server-received authenticated heartbeats rather than client wall clock, since endpoint clocks are not trusted. The server distinguishes agent state from network state and reports both, along with `last_heartbeat_at`, `last_seen_at`, `changed_at`, and whether an active WebSocket is currently registered. A socket connection alone is not a substitute for current heartbeat health.

The status pipeline is therefore: authenticated event arrives → connection identity identifies device → server receipt time is recorded → durable status is updated → state transition is recorded when applicable → an admin event invalidates relevant dashboard queries.

## Admin event stream

The browser connects to `/api/v1/admin/events` using its administrator cookie. This SSE channel is distinct from the agent WebSocket and sends small event names/payloads that tell feature views to refetch. It is intentionally not treated as a durable message queue: REST records remain the source of truth. Keep-alives support long-lived connections. Event distribution is in-process, so multi-worker deployment requires shared fan-out.

## Device lifecycle operations

Pending enrollment approval, rename, enable/disable, credential revocation and deletion are server-authorized operations. Privileged changes are audited. Device deletion needs special care because dependent telemetry and history can cascade; the durable audit snapshot preserves evidence of the deletion operation. A disabled, rejected, revoked or quarantined device cannot be treated as a normal active agent solely because its metadata remains in the database.

## Source map and limits

Room/layout and status routes are in `api.py`; transactional services are in `services.py`; models are in `models.py`; WebSocket heartbeat processing and active device map are in `websocket.py`; admin SSE fan-out is in `events.py`. The single-process active-device map and SSE hub are MVP constraints. Historical layout is not snapshotted for exam reports.
