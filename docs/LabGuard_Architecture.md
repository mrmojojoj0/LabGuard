# LabGuard Architecture Decision Record

Status: Phase 0 architecture baseline | Date: 2026-11-02

This resolves the complete technical outline for two independent Python deployables, targeting an initial fleet of about 50 Windows PCs. This is architecture planning only; it does not start Phase 1.

## Decisions and conflicts resolved

- Server: FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL. Use synchronous SQLAlchemy in the MVP for simpler transaction handling. Serve a same-origin Jinja2/HTMX admin UI from the server. No Redis, broker, separate frontend service, or microservices.
- Client: Windows Service in Python 3.12+, with Windows APIs isolated behind adapters; psutil for basic system/network collection and pywin32 only where required. No Session 0 desktop interaction. Defer an interactive helper.
- HTTPS handles admin APIs, enrollment, and bounded inventory uploads. WSS handles the persistent agent session, heartbeat, job delivery and job lifecycle. Do not duplicate heartbeat/job events over REST.
- PostgreSQL is authoritative. UUIDs and UTC timestamps throughout. Device UUID is persistent identity; per-device asymmetric key authenticates it. MAC, IP and hostname are changeable inventory attributes.
- Admin browser auth uses revocable server-side sessions in Secure/HttpOnly/SameSite cookies and CSRF protection. This resolves the outline's conflicting refresh-token and CSRF direction. Device credentials are separate from admin sessions.
- Enrollment code is short-lived, one-use, admin-created, rate-limited, and only creates a pending request. An administrator explicitly approves the UUID/public-key binding. Reinstall/key replacement requires approval. Revoke credentials server-side.
- Agent connection status derives only from authenticated server-received heartbeats. Network reachability is a separate signal and defaults UNKNOWN/NOT_CHECKED; ping is not online status.
- Jobs have a parent request and per-device target state; aggregate status is derived. Typed/versioned allowlisted operations only. No unrestricted shell, free-form command arguments, or arbitrary executable paths.
- At 50 PCs and 10-second heartbeats, one app instance and PostgreSQL are adequate. Start with a single WebSocket-serving instance; add complexity only after measurement.
- The outline lacks a Windows build baseline, hosting/TLS/certificate plan, admin account bootstrap, retention periods, privacy policy, and network constraints. Confirm these before production. Initial client target is Windows 10/11 x64 pending confirmation.
- Discovery scans, packet capture, DNS metadata, VPN heuristics, process termination, software deployment/direct installers, GUI automation, and self-updater are not MVP scope. Do not collect window titles or packet payloads by default. Set retention before collecting process/network history.

## Component boundaries

Server packages: api/v1 (routes and validation), services (business rules/transactions), models and repositories (SQLAlchemy persistence), security (RBAC/session/CSRF/device credentials), websocket (handshake/session/bounded send queue), web (same-origin UI), integrations (later package catalog). Routes stay thin. Durable jobs live in PostgreSQL; an in-memory connection map is only a delivery optimization.

Client packages: service orchestration; identity/key storage; HTTPS/WSS transport and reconnect; collectors; typed job validation/handlers and durable dedupe journal; Windows adapters. No shared runtime package between projects. Protocol compatibility is maintained by versioned schemas and this document.

## Database schema and relationships

All primary keys UUID; PostgreSQL TIMESTAMPTZ in UTC. Use JSONB only for bounded versioned payloads, not fields used for common filtering. Index foreign keys and query fields.

- administrators(id, normalized_username unique, password_hash Argon2id, role, enabled, created_at, last_login_at)
- admin_sessions(id, administrator_id FK, token_hash unique, csrf_secret/hash, created_at, expires_at, revoked_at, last_used_at); never store raw cookie token.
- enrollment_codes(id, code_hash, created_by FK, created_at, expires_at, consumed_at, revoked_at, max_uses=1)
- devices(id = persistent client UUID, assigned_name unique among active, hostname, enrollment_state, enabled, agent_version, OS fields, first_seen_at, last_seen_at, created/updated/archived timestamps)
- device_credentials(id, device_id FK, public_key/fingerprint, issued_at, not_after, revoked_at, replaced_by_id); private key stays on client.
- device_status(device_id PK/FK, agent_state, network_state, last_heartbeat_at server receipt, last_network_check_at, changed_at); device_status_events records transitions/reasons.
- device_interfaces(id, device_id FK, interface key/name/description/type, MAC, operational_state, observed_at); MAC is non-unique.
- device_ip_observations(id, interface_id FK, INET address, prefix, gateway, observed_at, valid_until); historical, no global uniqueness.
- rooms(id, active unique name, description, rows, columns, archived_at, timestamps)
- device_positions(device_id PK/FK, room_id FK, zero-based row/column, updated_at); unique(room_id,row,column), validate bounds transactionally. A device has at most one current placement.
- telemetry_samples(id, device_id FK, collected_at, received_at, CPU, memory bytes, uptime, bounded disk JSON); device_telemetry_latest keyed by device_id.
- inventory_snapshots(id, device_id FK, kind, collected_at, received_at, status, item_count, error_summary); software_inventory_items(snapshot_id FK, normalized_key, name/version/publisher/source/package_id/install_location), unique(snapshot_id,normalized_key). Process inventory deferred.
- jobs(id, kind, schema_version, requested_by FK, created_at, expires_at, approval_state, idempotency_key, parameters JSONB); unique(requested_by,idempotency_key).
- job_targets(id, job_id FK, device_id FK, state, accepted/started/completed timestamps, exit_code, bounded result, error_code, attempt_count); unique(job_id,device_id). States: QUEUED, OFFERED, ACCEPTED, RUNNING, SUCCEEDED, FAILED, CANCEL_REQUESTED, CANCELLED, TIMED_OUT, EXPIRED. Derive parent status.
- policies(id, name, policy_type, config JSONB, enabled, created_by FK, updated_at)
- audit_events(id, actor_type/id, optional device_id, action, target_type/id, result, occurred_at, request_id, bounded metadata); append-only.
- event_receipts(device_id, event_id, sequence, received_at) with unique(device_id,event_id) and unique(device_id,sequence), if durable replay dedupe is needed.

Relationships: administrator 1:M sessions, enrollment codes, and jobs; device 1:M credentials, interfaces, status events, telemetry, inventory and job targets; interface 1:M IP observations; room 1:M positions; job 1:M targets. Define per-table retention and backup/restore procedures before high-volume phases; keep latest values separate from history.

## REST contract

JSON under /api/v1 over TLS. Stable errors: {"error":{"code":"...","message":"...","request_id":"...","details":{}}}. Paginate lists with opaque cursor, default 50/max 200. Use version/If-Match or 409 for stale writes. Admin endpoints require session+role; device routes bind path UUID to authenticated credential. Privileged mutations and audit record commit together.

Admin/auth and enrollment:
- POST /auth/login (rate limited, sets session cookie and CSRF token); POST /auth/logout; GET /auth/me. No refresh endpoint in MVP; fixed absolute session expiry.
- POST /enrollment-codes (admin creates one-time TTL code; show plaintext once).
- POST /enrollment/request (rate limited; code, UUID, public key, hostname, OS, agent version, interfaces; pending only).
- GET /enrollment/requests; POST /enrollment/requests/{request_id}/approve or /reject. Approval binds key and can assign name/room; bootstrap credential shown once.
- POST /devices/{id}/credentials/rotate and /revoke; explicit authorized/audited action.

Admin resources:
- GET/POST /devices; GET/PATCH /devices/{id}; POST /devices/{id}/archive, /enable, /disable, /quarantine, /release.
- GET/POST /rooms; GET/PATCH/DELETE /rooms/{id} (delete only empty); PUT /rooms/{id}/layout with {rows,columns,assignments:[{device_id,row,column}]}, atomic replacement and collision/bounds rejection.
- GET /devices/{id}/telemetry, /interfaces, /inventory, /status-history.
- GET/POST /jobs; GET /jobs/{id}; POST /jobs/{id}/approve, /cancel, /retry (retry policy explicit).
- GET/POST /policies; GET/PATCH /policies/{id}; GET /audit-events; GET /health/live and /health/ready (DB check).
- Device ingestion: POST /devices/{id}/telemetry; PUT /devices/{id}/interfaces (replace current snapshot); POST /devices/{id}/inventory/software (snapshot UUID makes upload idempotent; later MVP if needed). Client cannot set authoritative status.
- Package catalog, process control, discovery, packet capture, advanced reports, and account management are outside MVP API scope. Same-origin UI; no broad CORS.

## WebSocket protocol

Endpoint wss://host/api/v1/agent/session. Authenticate with mTLS where available, otherwise a short-lived one-use WSS ticket minted over authenticated HTTPS and bound to device+credential. Never put long-lived secrets in URL. Reject pending/disabled/quarantined/revoked devices.

Envelope: {"protocol":"labguard.agent","schema_version":1,"event_id":"uuid","device_id":"uuid","sequence":12,"sent_at":"RFC3339 UTC","type":"client.heartbeat","payload":{}}. Limit frames to 64 KiB initially; validate strict schemas and increasing sequence. Duplicate event ID/sequence is acknowledged without reapplying. Server receipt time is authoritative; client timestamp is diagnostic only.

Client events: client.hello (agent/protocol version, boot_id), client.heartbeat (sequence, agent version, health), job.accepted, job.started, job.progress (bounded/rate-limited), job.completed/job.failed (code, bounded summary, exit code), client.status (diagnostic only). Server events: server.welcome (server time/heartbeat interval/config revision), server.ack, server.ping (transport keepalive only), job.offer (immutable target, expiry, typed params, approval reference), job.cancel (best effort), config.update (allowlisted settings). Agent update event reserved and disabled.

Persist target OFFERED before send. Client durably journals accepted/running/completed idempotency before side effects. Server DB is delivery source; reconnect may reoffer safely. Bound queues/results. Invalid or oversized messages close the session and emit a security log. WSS ping/pong is not an application heartbeat.

## Enrollment and heartbeat state machine

Enrollment flow: administrator creates short-lived one-use code; client generates and persists UUID+keypair; client submits pending request over verified TLS; server consumes code atomically and grants no privileges; admin reviews/approves binding; client stores issued credential via DPAPI/certificate store with restrictive ACL; WSS authenticates UUID, approved state, credential validity, and revocation on every connection. Rotate with authenticated old key and limited overlap; recovery requires admin-approved replacement. Audit all lifecycle and failure events.

Heartbeat period defaults to 10s; DELAYED at 30s; OFFLINE at 60s since last server receipt. Require heartbeat < delayed < offline. Approved device without first heartbeat is NEVER_CONNECTED. Authenticated hello/heartbeat sets ONLINE; age thresholds produce DELAYED/OFFLINE. DISABLED and QUARANTINED override liveness and block jobs. Socket close alone does not immediately mean offline. Persist last heartbeat and evaluate stale devices after server restart. Record every state transition and reason. Reachability is separate UNKNOWN unless explicitly checked. Client reconnect uses exponential backoff with full jitter and cap around 60s.

## Authorization and job allowlist

Roles: Viewer (read-only), Operator (request approved non-destructive collection), Lab Admin (devices/rooms/catalog/jobs), Super Admin (accounts, credentials, global settings, grants). Enforce per action and per job; approval must be satisfied before offer.

MVP jobs: COLLECT_SYSTEM_INFO, COLLECT_NETWORK_STATS (interface counters), RUN_APPROVED_DIAGNOSTIC (fixed built-in diagnostic IDs; no command text). Read-only. Later phases may add approved package-ID install/uninstall/upgrade, protected-process-safe termination with PID+start-time, and restart/shutdown with approval and user notice. No arbitrary shell, command text, executable path, covert UI, security bypass, or payload capture. All jobs have immutable typed params, requester, expiry, idempotency key, approval, per-device state, bounded output, and audit trail.

## Phase 0 completion and next step

Architecture review is complete when this document and both project AGENTS.md files are accepted. Do not start Phase 1 until the project owner authorizes it. Recommended next implementation task after authorization: server foundation with migrations, admin session/RBAC, pending/approved device registry, room/layout transaction, and audit; then the first end-to-end hello/heartbeat. Before production, confirm hosting OS, Windows baseline, TLS/certificate issuance, admin bootstrap, privacy/retention, and mTLS vs HTTPS-issued WSS ticket feasibility.

## Device authentication and heartbeat implementation detail

The first WSS milestone uses Ed25519 device keys and HTTPS-issued one-time tickets. Enrollment accepts only an Ed25519 SubjectPublicKeyInfo PEM; admin approval creates the active server-side device credential record. The private key remains on the client under DPAPI. Authentication uses POST /api/v1/agent/challenge followed by POST /api/v1/agent/ticket. The client signs UTF-8 bytes in this exact format: `labguard.device.auth.v1\\n{device_uuid}\\n{challenge_uuid}\\n{sha256_hex(nonce)}`. The ticket is random, stored only as a hash, bound to the device, expires quickly, and is sent in the WSS Authorization header for one-time claim. It never appears in a URL. This concretizes the previously selected short-lived WSS ticket option; long-lived key material never appears in a URL.

Connection lifecycle persists device_status, device_status_events, and device.last_seen_at. Default HEARTBEAT_INTERVAL_SECONDS=10, DEVICE_DELAYED_AFTER_SECONDS=30, DEVICE_OFFLINE_AFTER_SECONDS=60. Server receipt time updates status; a background evaluator handles delayed/offline state after missed heartbeats, including after server restart. Application heartbeat and WebSocket ping/pong remain distinct. The client persists its increasing sequence with its identity, and the server rejects replayed/non-increasing sequence values.
