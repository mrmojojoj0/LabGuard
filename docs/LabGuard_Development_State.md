# LabGuard Development State and Handoff

Updated: 2026-11-06  
Current baseline: v0.6 software inventory and package management corrections  
Next planned milestone: v0.7 Bulk Software Deployment (not started)

This document is the handoff entry point for a fresh agent session. Read it with `LabGuard_Architecture.md`, the relevant project `AGENTS.md` and README files. Verify the current Git state and code before editing; these files describe the current worktree, not a commit.

## Current project architecture

- `labguard-server`: FastAPI, Pydantic, SQLAlchemy and Alembic API/service. PostgreSQL is the intended deployment database. It owns administrator sessions/RBAC/CSRF, device identity and enrollment, rooms/layout, status, audit, telemetry, software inventory/catalog/jobs and authenticated WSS/SSE.
- `labguard-client`: Python 3.12 Windows agent. Foreground and pywin32 LocalSystem service modes use the same Ed25519 identity, HTTPS ticket issuance, ticket-authenticated WSS protocol, heartbeats, telemetry, software inventory, reconnect handling and durable job journal.
- `labguard-dashboard`: React/Vite/TypeScript app. It consumes the `/api/v1` REST and authenticated admin SSE interfaces; it never connects to the agent WebSocket.

The existing architecture preserves one server-side authority for device lifecycle and job state. Browser mutations use session cookies plus CSRF and server-side roles. Agent message device identity comes from its authenticated ticket. Private identity keys stay on clients under DPAPI. See `LabGuard_Architecture.md` for the protocol and current route summaries.

## Implemented milestones

- Foundation: administrator sessions and roles, audited enrollment and approval, Ed25519 credentials, one-time WSS tickets, device status, rooms and atomic layouts, audit events, dashboard, launch scripts, LAN/TLS configuration.
- v0.2 stabilization: current code includes the accepted LAN, administrator event stream, room editor, credential revocation and security hardening work. Consult the actual tests and Git diff for details.
- v0.3 Windows Service: pywin32 service management, startup/reconnect/stop behavior, service configuration, persistent identity state/DPAPI migration path, protected state directory, logging and same-identity process lock. Windows-only service, ACL and DPAPI behavior still needs on-device verification.
- v0.4 telemetry: bounded system snapshot collection/transmission, server persistence/history/retention and dashboard views. Collector work is isolated from heartbeat handling.
- v0.5 software inventory: registry/WinGet/Chocolatey inventory, batch persistence, partial-versus-complete reconciliation, freshness, manual refresh and dashboard views.
- v0.6 individual software management and corrections: approved package catalog with explicit pending/approved/rejected/revoked review status, typed persisted one-device jobs, WinGet/Chocolatey adapters, install/uninstall confirmation, progress/results, inventory verification and reconnect/deduplication. Inventory freshness treats PARTIAL as a successful snapshot while keeping last attempt, last successful, and last complete timestamps distinct. Registry view no longer determines app architecture; duplicate registry representations are normalized.

Do not implement telemetry expansion, bulk deployment, remote desktop, arbitrary shell, process termination, USB control or software auto-update as part of a v0.6 continuation.

## v0.6 catalog, security, and job flow

Super Admin creates catalog records and explicitly approves, rejects, or revokes them. Entries include display name, exact package ID, manager, publisher/description, version policy, scopes, source and approval metadata. Rejected entries stay available for review, but viewers and operators only receive approved catalog rows. Install/uninstall job creation is LAB_ADMIN+ with CSRF; catalog mutations are Super Admin with CSRF. Job reads are Viewer+. Server audit records catalog mutations and job requests.

WinGet is fixed to the community source; Chocolatey requires `CHOCOLATEY_SOURCE_URL` configured as HTTPS without embedded credentials/query/fragment. The client uses fixed argument lists and `shell=False`; no arbitrary download URL, executable path, uninstall string, shell, or PowerShell can be submitted. The server validates approved catalog identity, device availability, scope/version, uninstall inventory match, job expiry and active-job conflicts.

The job database record is committed before dispatch. Offline requests stay PENDING. An authenticated reconnect receives nonexpired pending work; DISPATCHED/RUNNING work may be offered again. The client persists ACCEPTED/RUNNING/terminal journal state before side effects, reports accepted/started/progress/completed/failed over the existing schema_version 1 WebSocket, and refreshes inventory. Success requires manager exit success and inventory confirmation. If it reconnects with an uncertain RUNNING journal entry, it reports `agent_restart_result_unknown` and does not run it again. Server events produce `software.job` SSE invalidations; dashboard queries use real REST job data.

Machine scope requires elevated administrator or LocalSystem. USER-scope jobs are refused in Session 0, including custom service accounts; the agent does not impersonate users or launch a helper. User-scope WinGet can only run from a foreground interactive process. Chocolatey is machine-only. Chocolatey may not remove the underlying native application for every package; the post-operation inventory check prevents reporting success based only on Chocolatey's exit code.

Migration `0005_software_jobs` adds the catalog, jobs, indexes and nullable job linkage on software inventory collections. Migration `0006_catalog_review_status` adds and backfills explicit review state. Migration head is 0006; the revision chain is 0001 through 0006. SQLite downgrade/upgrade is covered by tests. The app does not create schema on startup; apply `alembic upgrade head` before deployment.

## v0.6 inventory corrections

WinGet discovery checks PATH and the current execution identity's Windows App Execution Alias path. Query failures have separate diagnostic codes for missing executable, access denial, timeout, package registration, command failure and unusable output; logs record the failure class and safe environment-presence facts, never a full environment dump. Registry inventory continues if WinGet fails. The reported Krypton scenario has not been reproduced in the service or foreground process here, so its device-side root cause remains unconfirmed.

Registry view is treated only as the place metadata was read. Architecture uses explicit registry metadata, otherwise `UNKNOWN`; explicit architecture and install location preserve side-by-side installs while repeated identical entries collapse. A version update refreshes the same installation entry. Inventory status exposes latest attempt, last successful (including PARTIAL), and last complete timestamps. Freshness uses the latest successful snapshot; FAILED attempts do not erase prior inventory. A partial snapshot does not mark unobserved apps absent.

## Dashboard entry points

- `/software`: inventory summary, search/filter, aggregate installations and device details.
- `/deployment`: Super Admin catalog create/search/approve/revoke and fleet job monitor.
- Device details → Software: inventory freshness, approved catalog search, package-manager uninstall candidates, confirmation dialogs, and per-device job monitor.
- The admin SSE bridge invalidates software inventory and job queries on `software.inventory` and `software.job` events.

## v0.6 verification record

Recorded on 2026-11-06 after implementation:

- Server: `pytest -q` — **33 passed**, one Starlette/httpx deprecation warning.
- Client: `pytest -q` — **29 passed** in the available virtual environment.
- Dashboard: `npm test -- --run` — **12 passed** in 6 test files.
- Dashboard `npm run typecheck` — passed.
- Dashboard `npm run build` — passed; Vite warned the main JavaScript chunk is above 500 kB.
- Alembic `history` — head is `0006_catalog_review_status`.
- SQLite migration test upgraded to head, downgraded to 0004, and upgraded to head again — passed as part of server tests, including the 0006 review-status column.
- `git diff --check` — passed at the time of the final implementation review.

Automated manager tests use mocked subprocesses. No real software was installed or removed. There is no PostgreSQL migration run or real package-manager/service-context run recorded.

To rerun from the repository root:

~~~powershell
Set-Location .\labguard-server
.\.venv\Scripts\python.exe -m pytest -q

Set-Location ..\labguard-client
.\.venv\Scripts\python.exe -m pytest -q

Set-Location ..\labguard-dashboard
npm test
npm run typecheck
npm run build
~~~

## Known limitations and manual verification

1. Apply and verify migrations 0001–0006 against a disposable PostgreSQL database; SQLite passing does not prove PostgreSQL behavior.
2. On Krypton or a disposable Windows PC, capture the sanitized WinGet diagnostic under foreground and actual service execution, then verify discovery and machine install/uninstall. The current changes distinguish PATH/alias, access, timeout, App Installer registration, command and output errors, but actual service-context discovery remains unverified.
3. Verify Chocolatey machine install and uninstall against the configured managed feed. Check the underlying application, not only Chocolatey's package record.
4. Verify elevation requirements, Session 0 USER-scope rejection for LocalSystem and a custom service account, and foreground interactive WinGet user scope.
5. Verify real package-manager timeout, stop/cancellation and reconnect behavior on Windows. Current automated tests mock package processes and exercise the journal/event paths only.
6. Dashboard production build still emits the >500 kB chunk warning; no code splitting has been done.
7. The admin API docs/OpenAPI exposure needs an authenticated or ingress-restricted production policy.
8. A server-side job cancellation endpoint/flow is not implemented. `CANCELLED` exists in the persisted status vocabulary, but no administrator cancellation control is offered.
9. The v0.6 client reports uncertain in-progress work rather than retrying it automatically. An operator must inspect inventory before submitting a replacement job.

## Git/worktree safety

At the documentation handoff check, Git reported branch `main` at `4d10cf6 v0.6`; the v0.5/v0.6 source files are tracked in that commit. This documentation task has not committed code. The handoff doc/README/AGENTS edits are uncommitted. Recheck `git status --short` at the next session because that is the authoritative current state. Do not reset, clean, stash, discard, rewrite history, or commit unless explicitly requested.

## v0.7 planned scope — Bulk Software Deployment

v0.7 should extend the existing catalog and per-device `SoftwareJob` infrastructure; it must not create a second execution/job system. The current job is a single-device record, so bulk work will need an aggregate deployment/request identity linked to its per-device jobs for target selection, concurrency, reporting and audit. Treat that aggregate as coordination/history around the existing jobs, not a second agent execution queue. Planned requirements:

- Target multiple individually selected devices and room-based selections, with a server-side snapshot/validation of selected targets.
- Bulk installation and uninstallation using the existing approved package catalog, exact IDs, scopes and inventory rules.
- Configurable bounded concurrency; avoid flooding agents, database, package feeds or LAN links.
- Per-device job state and an aggregate deployment record/status, preserving failure isolation so one target does not stop others.
- Explicit retry and cancellation semantics with audit history and safe behavior for uncertain in-progress work.
- Deployment history and reporting by package, initiator, target/room, status, timing and result.

Before implementation, inspect `SoftwareJob`/`SoftwareCatalogPackage`, migration 0005, `software_jobs.py`, WebSocket offer/redelivery behavior, audit events and current dashboard routes. Define atomic target creation, partial failure, concurrency, cancellation, retry/idempotency and deleted/offline-device handling. Preserve schema_version 1 compatibility unless a documented protocol change is necessary. Do not start v0.7 until separately authorized.

## Fresh-session reading order

1. `docs/LabGuard_Development_State.md` (this handoff)
2. `docs/LabGuard_Architecture.md`
3. `labguard-server/AGENTS.md`, `labguard-client/AGENTS.md`, `labguard-dashboard/AGENTS.md`
4. Project READMEs and `docs/LabGuard_v0.5_Software_Inventory.md`, `docs/LabGuard_v0.6_Software_Management.md`
5. Inspect Git status/diff and the migrations/models/API/WSS/software job code before any implementation.
