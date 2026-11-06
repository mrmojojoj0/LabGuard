# LabGuard Architecture and Current Implementation

Status: Implemented foundation through v0.7 centralized WinGet discovery | Updated: 2026-11-07

This document describes the current repository architecture. The original Phase 0 baseline is retained below as historical context; where it differs from the current implementation described here, this current implementation section is authoritative. For the current worktree, milestone state and verification see `docs/LabGuard_Development_State.md`.

## Current system

LabGuard has three separate projects: a FastAPI/Pydantic/SQLAlchemy server in `labguard-server`, a Python 3.12 Windows agent in `labguard-client`, and a React/Vite/TypeScript dashboard in `labguard-dashboard`. PostgreSQL is the deployment database; server integration tests use SQLite and apply Alembic migrations. The dashboard is a separate development/build process and uses the server's same-origin `/api/v1` contract. The API and agent WebSocket run from the server; an authenticated admin Server-Sent Events endpoint supplies query invalidations to the dashboard.

The implemented server handles administrator sessions and role checks, CSRF-protected mutations, enrollment and approval, Ed25519 device credentials and single-use WebSocket tickets, rooms and atomic grid layouts, device status, audit events, telemetry, software inventory, centralized WinGet repository discovery, approved package catalog entries, and persistent individual software jobs. The dashboard provides fleet/device views, a room floor-plan editor, telemetry and history, inventory, audit, and software discovery/review/deployment pages. The client supports foreground execution and a Windows Service, protected identity state, heartbeat/reconnect, telemetry, local installed-software inventory, and v0.6 allowlisted WinGet/Chocolatey jobs. Do not infer product capabilities from placeholder navigation items.

### Identity, authorization, and audit

Administrator credentials use server-managed, revocable sessions in HttpOnly cookies. Browser mutations use the session CSRF token in `X-CSRF-Token`; role enforcement is server-side. Roles are VIEWER, OPERATOR, LAB_ADMIN, and SUPER_ADMIN. Device identities are persistent UUIDs bound to approved Ed25519 public keys; the private key stays client-side under DPAPI. The agent proves possession through HTTPS challenge/ticket endpoints; the short-lived ticket is stored hashed, single-use, device-bound, and presented in the WSS Authorization header. TLS verification stays enabled except for explicit local-development opt-in.

Audit records are written with their associated privileged database mutations. Device identity is derived from the authenticated ticket on ingestion; a payload's device ID is never sufficient authority. Deletion audit rows retain a text target and a bounded snapshot so they outlive device-owned cascades.

### Database and migrations

Migration head is `0006_catalog_review_status`, chained as 0001 foundation, 0002 device authentication/status, 0003 telemetry, 0004 software inventory, 0005 catalog/jobs, and 0006 explicit catalog review state. Model definitions are in `labguard-server/src/labguard_server/models.py`. The v0.5 inventory migration stores collections, unique batch receipts, and device software entries, with complete/partial reconciliation rules. Migration 0005 stores catalog approval metadata and software job state and adds nullable `software_inventory_collections.job_id` with `ON DELETE SET NULL`. Migration 0006 adds the indexed `approval_status` (`PENDING`, `APPROVED`, `REJECTED`, `REVOKED`) and backfills existing approvals. SQLite upgrade/downgrade/upgrade is tested. PostgreSQL migration execution has not been verified in this worktree.

### REST API

All routes are under `/api/v1`; the route implementation is `labguard-server/src/labguard_server/api.py`. Existing APIs include authentication, enrollment, device/credential lifecycle and deletion, rooms/layout, status, audit, telemetry, and software inventory. The v0.5 software inventory reads are `GET /devices/{id}/software`, `GET /software`, `GET /software/summary`, and `GET /software/{software_key}/installations`; an authorized administrator can request an online scan with `POST /devices/{id}/software/refresh`.

The v0.6 software-management endpoints are:

- Viewer+: `GET /software/catalog`, `GET /software/jobs`, `GET /devices/{id}/software/jobs`, and `GET /software/jobs/{job_id}`. Non-Super-Admin catalog reads return approved entries only.
- Super Admin + CSRF: `POST /software/catalog`, `POST /software/catalog/{package_id}/approve`, `/reject`, and `/revoke`.
- Super Admin: `GET /software/discovery/status`, `/software/discovery/sources`, and `/software/discovery/search?query=...&source=...`; Super Admin + CSRF: `POST /software/discovery/import`.
- LAB_ADMIN+ + CSRF: `POST /devices/{id}/software/jobs` (202 Accepted). A request targets one device; offline jobs remain pending.

Catalog package IDs are strict allowlisted identifiers. New entries begin as PENDING; Super Admin can review metadata and approve or reject them. Rejected entries remain in the catalog for audit and can be re-reviewed. Revocation removes an approved package from operator visibility. Only approved packages are returned to non-Super-Admin readers and can be used for jobs. No route accepts an arbitrary URL, executable path, PowerShell, CMD, or shell command. WinGet is fixed to its community source label. Chocolatey uses only `CHOCOLATEY_SOURCE_URL`, which must be HTTPS and contain no embedded credentials/query/fragment. Job requests and catalog create/review/approval/revocation actions are audited.

The server-side v0.7 discovery engine finds WinGet in the server process PATH, the current account's WindowsApps alias, or the Desktop App Installer package location, reports the current process identity/version, lists configured WinGet source names, and runs bounded `search --name` and exact `show --id` operations with argument arrays and `shell=False`. It parses WinGet's aligned text tables, including single-source results that omit the Source column by using the requested source name; it does not assume JSON output support. Search results can be imported as PENDING WINGET catalog entries and are deduplicated by case-insensitive package ID. The existing agent only executes WinGet packages from its fixed `winget` community source, so only results from that source can be imported into the deployable catalog; other configured sources remain searchable. Client inventory collection and remote execution remain client-side. Chocolatey code, tests, settings, and behavior are unchanged.

### Agent WebSocket and admin SSE

The existing authenticated WSS endpoint is `/api/v1/agent/session`; the envelope remains `protocol=labguard.agent`, `schema_version=1`, event UUID, device UUID, monotonic per-device sequence, timestamp, type and typed payload. Heartbeat, telemetry and software inventory use that session. Telemetry and inventory errors are isolated from heartbeat processing. Frames and nested payloads are bounded and validated.

Software inventory uses `client.software_inventory` and server acknowledgements. Administrator refresh uses `server.software_inventory.refresh` with a server-issued request UUID. v0.6 adds these typed events without changing the envelope version:

- Server to client: `server.software_job.offer` with job ID, action, package ID/manager, version, scope, approved source, expiry and timeout.
- Client to server: `client.job.accepted`, `client.job.started`, `client.job.progress`, `client.job.completed`, and `client.job.failed`.

The server binds events to the authenticated device, validates job ownership/state and sequence, persists each transition, and acknowledges the event. The authenticated admin SSE stream publishes `software.inventory` and `software.job` invalidations (also device status/connection/telemetry/deletion events). SSE carries invalidation metadata, not telemetry or secrets. The dashboard does not connect to the agent WSS endpoint.

### Individual software job lifecycle

`SoftwareCatalogPackage` requires Super Admin review before a job can reference it. Version policies are LATEST, PINNED, or SELECTABLE; scope is constrained by the package entry. An uninstall additionally requires a present inventory item with matching exact package ID, manager source and supported scope; registry uninstall command strings are never executed. The server allows only one active software job per device. Job statuses are PENDING, DISPATCHED, RUNNING, SUCCEEDED, FAILED, CANCELLED, or EXPIRED; the current REST interface does not provide an administrator cancellation operation even though CANCELLED is reserved in the model.

Jobs are persisted and audited before delivery. Offline jobs stay PENDING until an authenticated reconnect; expired work is not dispatched. DISPATCHED/RUNNING offers may be redelivered. The client writes a bounded durable journal before side effects; terminal results are replayed and a job interrupted while RUNNING is reported as uncertain instead of executed again. This prevents automatic duplicate execution at the cost of manual review/retry when completion is uncertain. The agent sends progress separately from heartbeat and runs collection/transmission outside the heartbeat loop. It reports success only when the manager exits successfully and a fresh inventory confirms the requested installed/removed state.

The package-manager adapters use fixed argument arrays with `shell=False`, bounded runtime/output, sanitized reporting, exact IDs, and safe executable discovery. WinGet discovery in the client checks the current account's WindowsApps alias and the machine App Installer package path under Program Files. WinGet MACHINE jobs are accepted only by the LocalSystem agent running in Session 0; an elevated foreground agent returns `privileged_service_unavailable`, and a non-elevated service returns an elevation error. The Windows service installer relies on pywin32's LocalSystem default and logs its runtime account, LocalSystem status, token elevation, and Session 0 status at startup. The client checks the process token's `TokenElevation` information and compares its SID to the LocalSystem well-known SID; failures are treated as non-elevated/non-System. USER-scope WinGet runs only in a foreground interactive agent process; Session 0 returns `user_scope_unavailable_in_service_session` because no safe interactive-session broker is implemented. WinGet process creation permission errors return scope-specific permission-denied codes. Chocolatey execution is unchanged and machine-only.

### Dashboard pages

`/rooms` provides visual room grid editing. Device details include overview, telemetry, and Software tabs. The Software Inventory page shows stored client inventory and device installations. `/deployment` provides Super Admin WinGet repository search, pending catalog import/review, and persisted job monitoring. The device Software page keeps its approved-catalog search and has a separate Super Admin Search WinGet Repository action; catalog typing calls the approved catalog API, while the explicit repository action calls the server discovery API. Both surfaces import discovered packages into the existing pending review flow. Admin-event SSE invalidates relevant React Query caches. Role-gated buttons supplement, but never replace, server authorization.

### Verified state and remaining verification

For the v0.7 discovery worktree, server 43 passed and dashboard 16 passed; dashboard typecheck and production build passed. PostgreSQL behavior and real WinGet operation under the server's deployed Windows identity remain environment-dependent checks. No client inventory, client job execution, or Chocolatey behavior was changed.

## Historical Phase 0 baseline

The following sections preserve the original architecture choices and threat-model context. They describe the initial target, not a complete list of current endpoints or current milestone status. The implemented REST, schema, and feature sections above supersede statements below that label software deployment as deferred, describe the database schema as planning-only, or list APIs that do not yet exist.

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
- telemetry_samples(id, device_id FK, collected_at, received_at, CPU, memory bytes/percent, weighted disk usage); device_telemetry_latest keyed by device_id with the bounded current snapshot, storage partitions, OS data, uptime, and interface metadata.
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
- GET /devices/{id}/telemetry and /devices/{id}/telemetry/history; GET /telemetry/summary. Viewer role or above. History is capped at 500 rows and retention-bound.
- GET/POST /jobs; GET /jobs/{id}; POST /jobs/{id}/approve, /cancel, /retry (retry policy explicit).
- GET/POST /policies; GET/PATCH /policies/{id}; GET /audit-events; GET /health/live and /health/ready (DB check).
- Device ingestion: POST /devices/{id}/telemetry; PUT /devices/{id}/interfaces (replace current snapshot); POST /devices/{id}/inventory/software (snapshot UUID makes upload idempotent; later MVP if needed). Client cannot set authoritative status.
- Package catalog, process control, discovery, packet capture, advanced reports, and account management are outside MVP API scope. Same-origin UI; no broad CORS.

## WebSocket protocol

Endpoint wss://host/api/v1/agent/session. Authenticate with mTLS where available, otherwise a short-lived one-use WSS ticket minted over authenticated HTTPS and bound to device+credential. Never put long-lived secrets in URL. Reject pending/disabled/quarantined/revoked devices.

Envelope: {"protocol":"labguard.agent","schema_version":1,"event_id":"uuid","device_id":"uuid","sequence":12,"sent_at":"RFC3339 UTC","type":"client.heartbeat","payload":{}}. Limit frames to 64 KiB initially; validate strict schemas and increasing sequence. Duplicate event ID/sequence is acknowledged without reapplying. Server receipt time is authoritative; client timestamp is diagnostic only.

Client events: client.hello (agent/protocol version, boot_id), client.heartbeat (sequence, agent version, health), client.telemetry (typed bounded CPU, memory, storage, OS, uptime, and interface snapshot), job.accepted, job.started, job.progress (bounded/rate-limited), job.completed/job.failed (code, bounded summary, exit code), client.status (diagnostic only). Server events: server.welcome (server time/heartbeat interval/config revision), server.ack, server.ping (transport keepalive only), job.offer (immutable target, expiry, typed params, approval reference), job.cancel (best effort), config.update (allowlisted settings). Agent update event reserved and disabled.

Persist target OFFERED before send. Client durably journals accepted/running/completed idempotency before side effects. Server DB is delivery source; reconnect may reoffer safely. Bound queues/results. Invalid or oversized messages close the session and emit a security log. WSS ping/pong is not an application heartbeat.

## Enrollment and heartbeat state machine

Enrollment flow: administrator creates short-lived one-use code; client generates and persists UUID+keypair; client submits pending request over verified TLS; server consumes code atomically and grants no privileges; admin reviews/approves binding; client stores issued credential via DPAPI/certificate store with restrictive ACL; WSS authenticates UUID, approved state, credential validity, and revocation on every connection. Rotate with authenticated old key and limited overlap; recovery requires admin-approved replacement. Audit all lifecycle and failure events.

Heartbeat period defaults to 10s; DELAYED at 30s; OFFLINE at 60s since last server receipt. Require heartbeat < delayed < offline. Approved device without first heartbeat is NEVER_CONNECTED. Authenticated hello/heartbeat sets ONLINE; age thresholds produce DELAYED/OFFLINE. DISABLED and QUARANTINED override liveness and block jobs. Socket close alone does not immediately mean offline. Persist last heartbeat and evaluate stale devices after server restart. Record every state transition and reason. Reachability is separate UNKNOWN unless explicitly checked. Client reconnect uses exponential backoff with full jitter and cap around 60s.

## Historical authorization and job allowlist proposal (superseded by v0.6 above)

Roles: Viewer (read-only), Operator (request approved non-destructive collection), Lab Admin (devices/rooms/catalog/jobs), Super Admin (accounts, credentials, global settings, grants). Enforce per action and per job; approval must be satisfied before offer.

The original plan proposed read-only diagnostic jobs and deferred package operations. v0.6 has since implemented approved individual install/uninstall jobs as documented in the current section above. Process termination, restart/shutdown, arbitrary shell, command text, executable paths, covert UI, security bypass, and payload capture remain out of scope.

## Historical Phase 0 planning gate

The initial Phase 0 architecture review and Phase 1 authorization gate are historical and have been superseded by the implemented milestones listed in this document and the current handoff in `LabGuard_Development_State.md`. Do not use the old foundation task list below as a statement of unfinished implementation. Production deployment still requires the outstanding checks recorded in Development State.

## v0.2 administrator event stream

The administrator dashboard uses a separate same-origin Server-Sent Events endpoint at `GET /api/v1/admin/events`. It requires a valid administrator session with at least VIEWER role and uses the existing HttpOnly session cookie. Events cover device status transitions, agent WebSocket connect/disconnect, telemetry invalidation, and device deletion; they contain device UUIDs, minimal status/timestamp/connection metadata, and never device credentials or private key material. The endpoint is a read-only stream, so it does not use CSRF tokens. It is an in-process, bounded fan-out for the existing single-server deployment; horizontal scaling requires a shared broker. EventSource handles reconnects; the dashboard invalidates relevant queries after each event.

## Device removal

`DELETE /api/v1/devices/{device_id}` requires an authenticated LAB_ADMIN or SUPER_ADMIN session and a valid CSRF token. The server locks and verifies the target, revokes its credential, writes a `device.delete` audit snapshot, and removes the device. Device-owned credentials, tickets, challenges, status, telemetry, software inventory, software jobs and room placement follow their configured foreign-key cascades; audit events remain queryable by text target ID. After commit, the server closes the active WebSocket and emits the `device.deleted` admin event. A deleted device must enroll and be approved again to reconnect.

## Device authentication and heartbeat implementation detail

The first WSS milestone uses Ed25519 device keys and HTTPS-issued one-time tickets. Enrollment accepts only an Ed25519 SubjectPublicKeyInfo PEM; admin approval creates the active server-side device credential record. The private key remains on the client under DPAPI. Authentication uses POST /api/v1/agent/challenge followed by POST /api/v1/agent/ticket. The client signs UTF-8 bytes in this exact format: `labguard.device.auth.v1\\n{device_uuid}\\n{challenge_uuid}\\n{sha256_hex(nonce)}`. The ticket is random, stored only as a hash, bound to the device, expires quickly, and is sent in the WSS Authorization header for one-time claim. It never appears in a URL. This concretizes the previously selected short-lived WSS ticket option; long-lived key material never appears in a URL.

Connection lifecycle persists device_status, device_status_events, and device.last_seen_at. Default HEARTBEAT_INTERVAL_SECONDS=10, DEVICE_DELAYED_AFTER_SECONDS=30, DEVICE_OFFLINE_AFTER_SECONDS=60. Server receipt time updates status; a background evaluator handles delayed/offline state after missed heartbeats, including after server restart. Application heartbeat and WebSocket ping/pong remain distinct. The client persists its increasing sequence with its identity, and the server rejects replayed/non-increasing sequence values.

## v0.3 Windows service hosting

The Windows client hosts the existing agent in a pywin32 LocalSystem service with automatic startup; its HTTPS ticket and WSS protocol remain unchanged. Foreground enrollment keeps current-user DPAPI protection. Before service installation, an explicit `service prepare` command, run under the enrolling Windows account, reads the existing identity and re-protects the same Ed25519 private key with machine-scope DPAPI. It fails if identity state is absent and never generates a replacement. A protected ProgramData ACL grants access only to the enrolling account, LocalSystem, and Administrators. The service config contains only the HTTPS URL and state path. A cross-process lock beside the identity prevents foreground and service instances from sharing one identity. This migration is local to the same Windows installation; identity files must not be copied to another computer. TLS validation stays enabled. Service stop cancels outstanding async work and closes the WebSocket; normal disconnects use capped jittered reconnects. Windows-only DPAPI migration, ACLs, service-control behavior and boot startup require manual OS verification recorded in the client README.

## v0.4 system telemetry

The client sends its first system snapshot after successful hello/welcome and continues every 30 seconds by default. `LABGUARD_TELEMETRY_INTERVAL_SECONDS` or the run/service CLI option configures intervals from 10 to 3600 seconds. Collection runs outside the heartbeat task. Collection and rejected-snapshot errors are isolated from heartbeat handling. Telemetry uses the existing ticket-authenticated WSS session and protocol schema version 1 with a new `client.telemetry` event; server acknowledgement includes the client event UUID and acceptance reason. The shared envelope device UUID must equal the device authenticated by the ticket, and is never an authorization input. The server caps frames at 64 KiB, strictly validates nested telemetry fields, and does not update heartbeat liveness or admin-managed device fields.

Metrics include CPU model, logical/physical counts and utilization; total/used/available memory; bounded disk partition capacity; Windows edition, version, build, architecture and hostname; boot time and uptime; and interface names, status, MAC, IPv4/IPv6 and link speed. The collector reads OS/system metadata only and does not inspect user files or browsing activity. Missing host values are nullable or represented by empty bounded lists.

`device_telemetry_latest` stores the newest full snapshot and `telemetry_samples` stores one indexed CPU/memory/weighted-disk row per accepted report. The server enforces `TELEMETRY_MIN_INTERVAL_SECONDS` (default 10), deletes old chart rows hourly and during ingest, and retains 30 days by default (`TELEMETRY_RETENTION_DAYS`). Current snapshots are considered stale after `TELEMETRY_STALE_AFTER_SECONDS` (default 120). Viewer-authenticated endpoints are GET `/api/v1/devices/{id}/telemetry`, GET `/api/v1/devices/{id}/telemetry/history?limit=120` (limit max 500), and GET `/api/v1/telemetry/summary`. The existing authenticated admin SSE stream emits a metrics-free `device.telemetry` invalidation event with device UUID and server receipt time.

Software inventory uses registry uninstall records plus optional local WinGet/Chocolatey listings. Registry view is not treated as product architecture: architecture comes only from explicit registry metadata and otherwise remains UNKNOWN. Identical representations across registry views are deduplicated using normalized source, scope, package/name, publisher, architecture, and install location; different explicit architectures or locations remain distinct. A version update refreshes the same installation entry. Optional manager failures produce source-specific diagnostics and do not discard registry entries. WinGet discovery checks PATH and the current execution identity's App Execution Alias location; logs include safe reason codes (missing executable, access denied, timeout, registration, command/output failure), the account/session, and whether the relevant user environment is present, without dumping environment values. This does not establish the cause of the Krypton report; its actual service/foreground execution context still requires device-side verification.

Inventory collection status separates latest attempt from freshness: COMPLETE and UNCHANGED are complete successes; PARTIAL is a successful, fresh snapshot with warnings and does not mark unseen software absent; FAILED and IN_PROGRESS do not overwrite the last successful snapshot. The API exposes latest attempt time/status, `last_successful_at` (including PARTIAL), `last_complete_at`, errors, and stale state computed from the most recent successful completion. Dashboard displays all three timestamps and distinguishes partial/current, failed attempt with prior snapshot, and stale inventory. Software inventory protocol, collection, schema, RBAC, API, and retention decisions for v0.5 are documented in `docs/LabGuard_v0.5_Software_Inventory.md`.

## v0.6 individual software management

Software management uses the existing ticket-authenticated WSS envelope (schema_version 1). The REST surface is `GET /software/catalog`, Super Admin `POST /software/catalog`, `POST /software/catalog/{package_id}/approve|reject|revoke`, LAB_ADMIN+ `POST /devices/{device_id}/software/jobs`, and Viewer+ job reads at `/software/jobs` and `/devices/{device_id}/software/jobs`. Mutations require the existing session, role check and CSRF token. Package IDs are strict identifiers; no executable paths or arbitrary download URLs are accepted. WinGet is pinned to its community source label. Chocolatey jobs use only the server-configured HTTPS `CHOCOLATEY_SOURCE_URL`.

The server persists reviewed catalog entries and software jobs in migrations `0005_software_jobs` and `0006_catalog_review_status`. Jobs store the target device, exact manager and package ID, action/version/scope, requesting administrator, expiry, progress and result. Offline jobs stay PENDING; reconnect delivers only nonexpired jobs. The server permits one active software operation per device and audits catalog review and job requests. Device event identity is taken from its authenticated WebSocket ticket. The typed server event `server.software_job.offer` carries the approved action and exact package details; client events `client.job.accepted`, `client.job.started`, `client.job.progress`, `client.job.completed`, and `client.job.failed` report lifecycle. This is an additive schema_version 1 event change. Reconnect can redeliver an offer; the agent's durable journal replays completed results and prevents repeating uncertain interrupted jobs. `software.job` SSE events invalidate dashboard job queries.

The client launches WinGet or Chocolatey with fixed argument arrays and `shell=False`, uses bounded timeouts and output capture, and scans inventory after the operation. A job succeeds only when the package-manager command exits successfully and the subsequent inventory confirms the requested state. USER-scope jobs are rejected in every Session 0 service process, including LocalSystem and custom service accounts. Machine scope requires elevation; Chocolatey is machine-only. LabGuard does not switch service accounts or launch an interactive helper. WinGet discovery accepts only the registered WindowsApps alias or Desktop App Installer package location; Chocolatey discovery accepts only its configured ProgramData path. Registry uninstall command strings are never executed.
