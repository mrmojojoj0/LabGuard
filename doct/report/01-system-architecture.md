# System Architecture and Data Flow

## Purpose and scope

LabGuard is a Windows lab fleet management system with three separately deployable projects: a Python Windows endpoint agent, a FastAPI server, and a React administrative dashboard. PostgreSQL is the intended deployment database. The components communicate through a versioned REST API and an authenticated device WebSocket; the dashboard uses same-origin REST and a distinct administrator Server-Sent Events (SSE) stream. The browser never joins the device channel.

The architecture is organized around durable server records and typed operations. Device identity is a UUID backed by a device key, administrator authority is role-checked on the server, and agent requests are constrained schemas. There is no general-purpose remote shell or arbitrary command path.

## Component responsibilities

| Component | Main responsibility | Representative modules |
| --- | --- | --- |
| Dashboard | Admin UI, user input, rendering server state and persisted job/evidence results | `labguard-dashboard/src/features/*`, `src/lib/api.ts` |
| Server | Authentication, authorization, validation, persistence, scheduling, event routing, report assembly | `labguard-server/src/labguard_server/api.py`, `services.py`, feature service modules |
| Windows agent | Device identity, heartbeat, collection, bounded typed job execution, event delivery | `labguard-client/src/labguard_client/agent.py`, feature adapters |
| Database | Durable devices, credentials, jobs, telemetry, audit, exam and evidence records | `models.py`, Alembic migrations |

The server's API routes should remain thin: they parse validated requests, call domain services, and serialize results. Domain modules own state transitions and persistence rules. SQLAlchemy models define durable state; Alembic migrations evolve the schema. The dashboard feature API modules centralize HTTP access and carry cookies and CSRF tokens as required.

## Main request and event pipelines

### Administrator command pipeline

1. An administrator signs in through `/api/v1/auth/login`; the server validates the password and creates a revocable server-side session.
2. The browser receives an HttpOnly session cookie and a CSRF token kept in application memory/session context. Mutations send the token in `X-CSRF-Token`.
3. A dashboard feature API submits a typed, versioned request. The server validates the Pydantic schema, role, CSRF token, target state, and feature-specific authorization.
4. For stateful actions, the server commits the record and its audit event transactionally before notifying a connected agent or publishing a dashboard invalidation.
5. Agent work travels over that device's authenticated WebSocket as a fixed event type and payload. The agent validates the version, identifier, expiry, target and allowlisted operation before performing a local adapter action.
6. The agent sends typed lifecycle/result events. The server derives device authority from the authenticated connection, validates and persists the result, then publishes an admin SSE invalidation.
7. The dashboard refetches canonical REST state and renders persisted server data. SSE is an invalidation mechanism, not a source of authoritative job state.

Offline behavior varies by feature. Some durable jobs remain pending for later delivery; immediate operations such as process requests or RDP preparation require an online connection and fail explicitly. Evidence capture requests may have a due time and expire/fail if no agent is available. The feature reports document these policies separately.

### Agent collection pipeline

1. Agent startup loads its persistent device UUID and key from protected local state, then authenticates to the configured server using TLS verification.
2. It reconnects with bounded exponential backoff and jitter and opens a ticket-authenticated WebSocket after an HTTP challenge/ticket exchange.
3. Periodic or requested collectors gather bounded local data. Collection errors are represented separately from a successful empty result.
4. Typed batches are sent over the authenticated channel. Acknowledgements gate cursor advancement where replay or loss matters (notably WFP event records).
5. Server ingestion attributes records to the connection's device identity, deduplicates where needed, persists, and updates derived status.

## Architectural constraints

- Device UUID and key prove identity. Hostname, MAC address, and IP address are mutable inventory attributes.
- TLS certificate verification is required outside the explicit development opt-in. No plaintext fallback is implicit.
- Agent jobs are typed and allowlisted. Package operations use fixed argument lists, `shell=False`, bounded duration/output, and exact package identity checks.
- The client runs as a Windows service in the supported deployment, typically LocalSystem. Machine operations and user-scope operations have distinct execution-context rules. User impersonation is not used.
- The dashboard uses same-origin APIs, cookie credentials and CSRF protection. Server-side RBAC is authoritative.
- Admin SSE and active device connections are in-process MVP infrastructure. A multi-worker deployment needs shared event fan-out and scheduler coordination.

## Runtime and persistence overview

The API and dashboard are separate processes during development. The server owns the agent WebSocket and admin SSE endpoints. PostgreSQL is the deployment database; the test suite may use SQLite, which does not establish PostgreSQL operational correctness. Large screenshot files use the screenshot service's configured file storage, with metadata in the database. WFP event data, telemetry snapshots, jobs and audit events have separate records and retention behavior.

## Failure and recovery model

The system prefers explicit failure states over success inferred from a request being sent. Jobs have durable lifecycle states; package install success requires a fresh inventory verification. Agent delivery can be interrupted, so job IDs and local idempotency journals protect against duplicate execution. WFP cursors advance only after acknowledged delivery. Exam screenshot failure does not erase the underlying violation. Expiry is part of request validation for short-lived capabilities.

## Boundaries and incomplete capabilities

Exam records currently describe desired policy and detected activity; endpoint blocking/enforcement is not implemented. The dashboard can only represent what the server API supports. Bulk deployment is not an independently implemented job engine; any future expansion must reuse the existing software job model and define fan-out semantics. Multi-instance coordination, production deployment hardening, live Windows service/package-manager behavior, and PostgreSQL migration verification remain operational validation items.

## Source map

Start with `docs/LabGuard_Architecture.md` and `docs/LabGuard_Development_State.md`. Server entry points are `api.py`, `main.py`, and `websocket.py`; client transport and loops are in `agent.py`; browser transport is in `labguard-dashboard/src/lib/api.ts` and feature API modules.
