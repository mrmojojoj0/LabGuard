# LabGuard Development State and Handoff

Updated: 2026-11-07
Current baseline: direct and bulk software installation, unified inventory, catalog-independent safe uninstall, and temporary managed RDP access
Next: controlled Windows endpoint validation of software flows and RDP lease setup/expiry; bulk targeting continues to use existing per-device jobs

This document is the handoff entry point for a fresh agent session. Read it with `LabGuard_Architecture.md`, the relevant project `AGENTS.md` and README files. Verify the current Git state and code before editing; these files describe the current worktree, not a commit.

## Current project architecture

The current dashboard supports direct repository search, individual PC or whole-lab target selection, scope selection, confirmation, persistent per-device job monitoring, post-success inventory refresh, and a LAB_ADMIN Remote Access tab for temporary RDP. See the current direct install, bulk target, and RDP sections below; these supersede older v0.6/v0.7 handoff descriptions further down.

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
- v0.7 centralized WinGet discovery: the server detects its WinGet executable/version and execution identity, lists configured source names, searches repository packages, retrieves metadata for exact package IDs, and adds selected results as deduplicated PENDING catalog entries. Super Admin review/approval and existing individual deployment jobs remain the authority. Clients continue collecting local installed-software inventory and executing jobs. Chocolatey implementation and behavior are unchanged.

Do not implement telemetry expansion, bulk deployment, remote desktop, arbitrary shell, process termination, USB control or software auto-update as part of a v0.6 continuation.

## v0.6 catalog, security, and job flow

Super Admin creates catalog records and explicitly approves, rejects, or revokes them. Entries include display name, exact package ID, manager, publisher/description, version policy, scopes, source and approval metadata. Rejected entries stay available for review, but viewers and operators only receive approved catalog rows. Install/uninstall job creation is LAB_ADMIN+ with CSRF; catalog mutations are Super Admin with CSRF. Job reads are Viewer+. Server audit records catalog mutations and job requests.

WinGet is fixed to the community source; Chocolatey accepts a configured `CHOCOLATEY_SOURCE_URL` using HTTP or HTTPS without embedded credentials/query/fragment. The client uses fixed argument lists and `shell=False`; no arbitrary download URL, executable path, uninstall string, shell, or PowerShell can be submitted. The server validates approved catalog identity, device availability, scope/version, uninstall inventory match, job expiry and active-job conflicts.

The job database record is committed before dispatch. Offline requests stay PENDING. An authenticated reconnect receives nonexpired pending work; DISPATCHED/RUNNING work may be offered again. The client persists ACCEPTED/RUNNING/terminal journal state before side effects, reports accepted/started/progress/completed/failed over the existing schema_version 1 WebSocket, and refreshes inventory. Success requires manager exit success and inventory confirmation. If it reconnects with an uncertain RUNNING journal entry, it reports `agent_restart_result_unknown` and does not run it again. Server events produce `software.job` SSE invalidations; dashboard queries use real REST job data.

v0.7.1 stabilizes WinGet execution context. MACHINE jobs require the LocalSystem Windows Service in Session 0; foreground agents return `privileged_service_unavailable`, even when elevated. The client reads the Windows process token's elevation state and compares the token SID to the LocalSystem SID, failing closed on access errors. USER-scope WinGet is supported from a foreground interactive agent and rejected with `user_scope_unavailable_in_service_session` when the service receives it. The service logs its account, System SID status, elevation, and session at startup. WinGet process-creation access failures report `machine_scope_permission_denied` or `user_scope_permission_denied`. A service-to-interactive-session broker is not implemented, so service-originated USER jobs cannot run. The Chocolatey execution path and behavior are unchanged. Chocolatey may not remove the underlying native application for every package; the post-operation inventory check prevents reporting success based only on Chocolatey's exit code.

Migration `0005_software_jobs` adds the catalog, jobs, indexes and nullable job linkage on software inventory collections. Migration `0006_catalog_review_status` adds and backfills explicit review state. Migration `0007_inventory_discovery_sources` adds nullable JSON inventory source provenance. Migration head is 0007; the revision chain is 0001 through 0007. SQLite downgrade/upgrade is covered by tests. The app does not create schema on startup; apply `alembic upgrade head` before deployment.

## v0.6 inventory corrections

WinGet discovery checks PATH and the current execution identity's Windows App Execution Alias path. Query failures have separate diagnostic codes for missing executable, access denial, timeout, package registration, command failure and unusable output; logs record the failure class and safe environment-presence facts, never a full environment dump. Registry inventory continues if WinGet fails. The reported Krypton scenario has not been reproduced in the service or foreground process here, so its device-side root cause remains unconfirmed.

Registry view is treated only as the place metadata was read. Architecture uses explicit registry metadata, otherwise `UNKNOWN`; explicit architecture and install location preserve side-by-side installs while repeated identical entries collapse. A version update refreshes the same installation entry. Inventory status exposes latest attempt, last successful (including PARTIAL), and last complete timestamps. Freshness uses the latest successful snapshot; FAILED attempts do not erase prior inventory. A partial snapshot does not mark unobserved apps absent.

## Dashboard entry points

- `/software`: inventory summary, search/filter, aggregate installations and device details.
- `/deployment`: Super Admin WinGet source search/import, catalog create/search/approve/revoke, and persisted job monitor.
- Device details → Software: inventory freshness, approved catalog search, a separate Super Admin Search WinGet Repository action, package-manager uninstall candidates, confirmation dialogs, and per-device job monitor. Typing into approved package search continues to call only the catalog API.
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
4. On a controlled Windows endpoint, inspect the service startup log and verify its LocalSystem token and Session 0 identity; install Mozilla Firefox through a MACHINE job and confirm it with a fresh inventory scan.
5. Verify USER-scope installation through a foreground interactive agent and confirm a service-originated USER job is rejected with the documented error.
6. Verify missing service, service stopped, and permission-denied cases on Windows. These real endpoint checks cannot be performed on the development host because `LabGuardAgent` is not installed there.

7. Verify real package-manager timeout, stop/cancellation and reconnect behavior on Windows. Current automated tests mock package processes and exercise the journal/event paths only.
8. Dashboard production build still emits the >500 kB chunk warning; no code splitting has been done.
9. The admin API docs/OpenAPI exposure needs an authenticated or ingress-restricted production policy.
10. A server-side job cancellation endpoint/flow is not implemented. `CANCELLED` exists in the persisted status vocabulary, but no administrator cancellation control is offered.
11. The v0.6 client reports uncertain in-progress work rather than retrying it automatically. An operator must inspect inventory before submitting a replacement job.

### Development-only HTTP for Windows Service

The client accepts HTTP and HTTPS server URLs in foreground and service modes. HTTPS retains normal certificate verification. Legacy `--insecure-dev` flags and the persisted `allow_insecure_dev` field remain accepted for config/CLI compatibility but are not required to use HTTP. Both transports continue through the same device identity, signed challenge, one-use ticket, enrollment, and authorization checks.

Verification: client suite **36 passed** using `labguard-client/.venv/Scripts/python.exe -m pytest -q`. Coverage verifies HTTP rejection by default, explicit HTTP acceptance, HTTPS acceptance, opt-in persistence/reload, service startup honoring the saved flag, CLI propagation for prepare/install, install-time explicit opt-in enforcement, and mocked ACL construction/assignment. No real Windows Service or ACL test was performed. Krypton verification is still required to test prepare/install/start against the local development server, inspect the protected ACL, and confirm production HTTPS behavior remains unchanged. Do not use the HTTP option for Krypton or production.

### Windows service preparation ACL correction

`secure_state_directory()` now uses `win32con.GENERIC_ALL` for the access mask passed to `AddAccessAllowedAceEx`, instead of the unavailable `win32con.FILE_ALL_ACCESS` attribute. Windows maps the generic access mask to file/directory rights. The protected DACL remains limited to the enrolling user SID, LocalSystem, and built-in Administrators; both object and container inheritance flags remain set. The existing machine-DPAPI identity migration was not changed.

Verification: full client suite **36 passed**. The new mocked Windows API test checks the exact three allowed SIDs, full access mask, inherited ACE flags, protected DACL flags, and assignment to the state directory and existing files only. This is not a live Windows ACL check. On Krypton, rerun service preparation in a controlled account and inspect the resulting ACL and machine-DPAPI service startup before treating the service setup as verified.

### Windows Service startup error 1053 investigation

The current Krypton worktree was inspected directly. The service registry has `PythonClass=labguard_client.windows_service.LabGuardWindowsService`, `ImagePath="C:\Users\sakin\Downloads\LabGuard\labguard-client\.venv\pythonservice.exe"`, `ObjectName=LocalSystem`, and automatic start. `.venv\pyvenv.cfg` is next to this root-level host and points to the base Python under `%LOCALAPPDATA%`. The service has no PythonPath value; the queried machine Python registry keys are absent. The base Python directory is on the interactive user's PATH but absent from the machine PATH. The ProgramData and Python/venv ACLs grant SYSTEM access.

Pywin32's installed `LocatePythonServiceExe()` places its host in `sys.exec_prefix`; with a venv, that is the venv root. The venv interpreter is under `.venv\Scripts`, where the parent `.venv\pyvenv.cfg` makes CPython resolve `.venv\Lib\site-packages`. The registered root-level host instead resolves the wrong prefix and misses `servicemanager` and the installed service module. The service environment also cannot rely on the user's PATH to load Python DLLs. This matches the pre-callback failure: `ServiceFramework.SvcRun()` reports `SERVICE_RUNNING` before `SvcDoRun()`, and no callback log exists. The direct `-debug` command's message is consistent with the import failure but is not used as proof.

The installer now stages `pythonservice.exe` in `.venv\Scripts` and copies the matching `python312.dll`, `pywintypes312.dll`, and `pythoncom312.dll` beside it. It registers that executable through pywin32's `exeName` option. If a venv service is already installed and stopped, `service install` updates its image path via `ChangeServiceConfig`; it leaves the existing LocalSystem identity and automatic startup unchanged. The class module retains its lightweight imports; full agent/network imports are deferred until after pywin32 reports RUNNING. Startup logs runtime paths and captures config, identity, and agent initialization exceptions in the protected ProgramData log. STOP and SHUTDOWN signal the event loop.

Verification: client suite **40 passed** (`labguard-client/.venv/Scripts/python.exe -m pytest -q`). Tests cover host/DLL staging, service registration/update path, preserving the existing service account settings, early RUNNING status, startup exception logging, and stop/shutdown signaling. The registry, venv config, machine/user PATH, DLL locations, and ACLs were inspected locally on Krypton. A venv Python import check with the machine PATH and no `PYTHONPATH` successfully imported `servicemanager` and the registered service class; this check ran as the interactive user, not LocalSystem. The new host and matching DLLs were staged under `.venv\Scripts`, but attempting `service install --insecure-dev` returned `OpenSCManager: Access is denied`; the service ImagePath therefore remains unchanged. The corrected host has **not yet been started through SCM**, so import under the actual LocalSystem token and live authenticated connection remain pending. Re-run the README install/update command in elevated PowerShell; inspect server job state before starting because the agent can receive existing approved jobs.

## Git/worktree safety

At the documentation handoff check, Git reported branch `main` at `4d10cf6 v0.6`; the v0.5/v0.6 source files are tracked in that commit. This documentation task has not committed code. The handoff doc/README/AGENTS edits are uncommitted. Recheck `git status --short` at the next session because that is the authoritative current state. Do not reset, clean, stash, discard, rewrite history, or commit unless explicitly requested.

## v0.7 WinGet discovery verification

- Server: pytest -q — 43 passed, one existing Starlette/httpx deprecation warning.
- Dashboard: npm test -- --run — 16 passed; npm run typecheck passed; production build passed with the existing >500 kB JavaScript chunk warning.
- Discovery process calls are mocked. Live WinGet behavior under the deployed server identity remains to be verified on the target Windows server.
## Future bulk deployment design (not started)

Bulk deployment remains future work and was not part of the v0.7 WinGet discovery implementation. It should extend the existing catalog and per-device `SoftwareJob` infrastructure; it must not create a second execution/job system. The current job is a single-device record, so bulk work will need an aggregate deployment/request identity linked to its per-device jobs for target selection, concurrency, reporting and audit. Treat that aggregate as coordination/history around the existing jobs, not a second agent execution queue. Possible requirements:

- Target multiple individually selected devices and room-based selections, with a server-side snapshot/validation of selected targets.
- Bulk installation and uninstallation using the existing approved package catalog, exact IDs, scopes and inventory rules.
- Configurable bounded concurrency; avoid flooding agents, database, package feeds or LAN links.
- Per-device job state and an aggregate deployment record/status, preserving failure isolation so one target does not stop others.
- Explicit retry and cancellation semantics with audit history and safe behavior for uncertain in-progress work.
- Deployment history and reporting by package, initiator, target/room, status, timing and result.

Before implementation in a later milestone, inspect `SoftwareJob`/`SoftwareCatalogPackage`, migration 0005, `software_jobs.py`, WebSocket offer/redelivery behavior, audit events and current dashboard routes. Define atomic target creation, partial failure, concurrency, cancellation, retry/idempotency and deleted/offline-device handling. Preserve schema_version 1 compatibility unless a documented protocol change is necessary. No later milestone was started by this change.

## Fresh-session reading order

1. `docs/LabGuard_Development_State.md` (this handoff)
2. `docs/LabGuard_Architecture.md`
3. `labguard-server/AGENTS.md`, `labguard-client/AGENTS.md`, `labguard-dashboard/AGENTS.md`
4. Project READMEs and `docs/LabGuard_v0.5_Software_Inventory.md`, `docs/LabGuard_v0.6_Software_Management.md`
5. Inspect Git status/diff and the migrations/models/API/WSS/software job code before any implementation.

## Windows Service cryptography DLL search-path correction

The current Krypton report confirms the SCM successfully enters `SvcDoRun`, loads service configuration, and then fails importing `cryptography.hazmat.bindings._rust` with `DLL load failed ... The specified module could not be found`. Inspection of the installed Python 3.12.7/cryptography 46.0.7 environment showed that `_rust.pyd` imports `python3.dll`. That DLL is in the base Python directory named by `.venv\pyvenv.cfg`; the interactive user's PATH contains that directory, but the LocalSystem machine PATH does not. The existing service staging copied `python312.dll` and pywin32 DLLs beside its `.venv\Scripts\pythonservice.exe`, but not `python3.dll`.

`windows_service._prepare_native_dll_search()` now registers `sys.base_prefix` through `os.add_dll_directory()` before the service imports `DeviceIdentity` and its cryptography dependencies. It verifies that `python3.dll` exists in that runtime directory, logs the registered path, and retains the returned handle for the lifetime of the process. It does not copy DLLs, modify System32, change the LocalSystem account, alter identity/DPAPI, or change HTTP/HTTPS, WSS, job, Chocolatey, or WinGet behavior. The existing `logger.exception()` path preserves full startup tracebacks.

Regression coverage verifies runtime DLL directory registration and handle retention. Client full suite: **42 passed** (`labguard-client/.venv/Scripts/python.exe -m pytest -q`). `git diff --check`: **passed**; Git emitted only line-ending normalization warnings for the existing modified files. These checks do not establish import success or authenticated startup under LocalSystem. On Krypton, from elevated PowerShell and the client root, rebuild/update and start using the exact commands in `labguard-client/README.md`; confirm the SCM reports RUNNING, the service log records `Registered Python native runtime DLL directory` followed by identity load and authenticated connection, and the enrolled identity UUID/key are unchanged. Service account remains LocalSystem. The current service registration may still point at the old root-level `pythonservice.exe`; `service install --insecure-dev` updates a stopped service to `.venv\Scripts\pythonservice.exe` while preserving its account.

## Windows Service asyncio loop thread correction

Krypton now confirms service startup proceeds through configuration load, registration of the base Python DLL directory, and loading the existing machine-DPAPI identity. It then failed at `asyncio.new_event_loop()` with `ValueError: set_wakeup_fd only works in main thread of the main interpreter`. pywin32 calls `SvcDoRun` outside the Python main thread; Python 3.12's default Windows event-loop policy selected a Proactor loop that configures signal wakeup handling.

The Windows Service now constructs `asyncio.SelectorEventLoop()` explicitly and installs it using `asyncio.set_event_loop()` in the calling service thread. This is scoped to service startup; foreground CLI behavior is unchanged. `SvcStop` and `SvcShutdown` continue to set the service stop flag and signal the loop's `asyncio.Event` via `call_soon_threadsafe`. Cleanup cancels pending tasks, closes the loop, and clears it from that same thread. WebSocket/reconnect, telemetry, inventory and software-job code paths are unchanged.

Regression coverage starts a SelectorEventLoop in a worker thread, confirms it is installed in that thread, and signals graceful completion via the production thread-safe stop helper. Client full suite: **43 passed** (`labguard-client/.venv/Scripts/python.exe -m pytest -q`). `git diff --check`: **passed**, with only Git's existing line-ending normalization warnings. These tests do not prove Krypton SCM operation. Use the README's exact elevated PowerShell build/install/start commands, then verify RUNNING state, authenticated connection, service stop, and restart in the ProgramData log. Preserve the existing enrolled identity and LocalSystem account; do not rerun identity preparation unless required for a separate controlled reason.

## LocalSystem WinGet discovery correction

Inspection found that WinGet job execution already searched the current account's WindowsApps alias and the machine App Installer package directory under `ProgramFiles`, but software inventory searched only PATH and the current execution identity's alias. In Session 0, LocalSystem has a system profile and machine PATH, not the interactive user's profile/PATH, so inventory could report `winget_executable_not_found` while the machine package was present.

Added `winget_discovery.py` as the shared executable resolver used by both inventory and job execution. It checks the current identity alias plus App Installer package directories under `ProgramW6432`, `ProgramFiles`, and `ProgramFiles(x86)`. It considers PATH only if the resolved executable equals one of those known locations; an arbitrary executable found through PATH is rejected. This gives LocalSystem a machine-wide lookup independent of an interactive user and keeps inventory and execution pointed at the same executable. Chocolatey code and behavior were not changed.

Regression tests cover machine package discovery with a LocalSystem-like environment that has no `LOCALAPPDATA` and no useful PATH, equivalent executable selection for inventory and job execution, alias lookup, and missing-executable reporting. Client full suite: **45 passed** (`labguard-client/.venv/Scripts/python.exe -m pytest -q`). `git diff --check`: **passed**, with only Git's line-ending normalization warnings. These mocked path tests do not verify access to the actual WindowsApps package ACL or App Installer registration under Krypton's LocalSystem token. Next, use Krypton to confirm the service inventory scan detects WinGet and the existing machine-scope installation workflow can launch it; inspect separate errors for package registration or permission denial if executable discovery succeeds. Do not change the service account or rerun identity preparation for this work.

## WinGet installation and inventory audit (2026-11-07)

Audit found three concrete defects: inventory passed unsupported winget list --count 2000 (WinGet accepts at most 1000), the LocalSystem privilege gate called pywin32 EqualSid which is absent in the installed module and therefore failed closed, and WSS ingestion reused the 300-second manual refresh cooldown, causing normal/reconnected inventory collections to receive inventory_rate_limited.

Fixes in the current worktree: cap WinGet list at 1000; compare current token SID and well-known LocalSystem SID via ConvertSidToStringSid; configure a separate 10-second inventory ingest minimum (bounded 1-60), return `retry_after_seconds` and retry once in the client. WinGet inventory and install share the machine-aware executable resolver. Existing discovery/import/approval, catalog authorization, fixed-argument job execution, durable lifecycle, fresh-inventory verification, Registry collection and dashboard views were audited as implemented. No uninstall work was started; Chocolatey adapters and behavior were not changed.

Verification: client full suite 48 passed; server full suite 45 passed (one existing Starlette/httpx deprecation warning); dashboard 16 passed, typecheck and production build passed (existing large-chunk warning); git diff --check passed with line-ending normalization warnings. Local service inspection showed RUNNING as LocalSystem in Session 0 and authenticated WSS in the protected log. The database had no PENDING, DISPATCHED, or RUNNING jobs. This environment did not execute a real package install as LocalSystem; mocked tests do not prove the WinGet package ACL or installer behavior. On the live endpoint, verify the next complete inventory and then run one approved machine-scope package install, confirm the lifecycle reaches SUCCEEDED only after a fresh inventory, and inspect permission-denied/service-unavailable behavior. Next task: perform that controlled Windows endpoint verification; do not start uninstall or bulk deployment.

## Unified installed-software inventory and row uninstall (2026-11-07)

The client now reconciles WinGet and Registry inventory before batching. It merges only unique compatible pairs: exact package ID when available, otherwise normalized name plus an equal nonempty publisher or version. Known package ID, edition, version, publisher, architecture, or scope conflicts reject a merge; ambiguous candidates remain separate. Unknown architecture/scope can be filled from Registry. Source-aware entry keys preserve variants, and reconciled rows prefer WINGET while retaining all contributing sources. Migration 0007 adds nullable JSON `discovery_sources`; legacy rows fall back to their existing `source` value.

The device Installed Software table is the single uninstall surface. Supported rows require exactly one approved catalog package with matching manager, exact package ID, and supported scope. Other rows remain visible with an explanation. Confirmation queues the existing audited individual software job. The client continues using only fixed WinGet arguments or the unchanged Chocolatey adapter, with no shell, registry uninstall strings, force option, UAC automation, or direct deletion. It reports success only after the package manager exits successfully and a complete fresh inventory confirms absence. The dashboard shows submitted job state/progress/result/error beside the row and invalidates inventory after verified success.

Regression coverage includes source reconciliation/provenance, name and package ID collisions, version/architecture/scope/edition conflicts, missing metadata, ambiguous/unmatched Registry rows, determinism, migration upgrade, uninstall authorization/unsupported targets, client post-uninstall complete-scan verification, and row confirmation/status/error UI. Chocolatey adapter regression tests remain in place and its command implementation was not changed.

Verification: client full suite **55 passed**; server full suite **48 passed** with one existing Starlette/httpx deprecation warning; dashboard suite **20 passed**, typecheck and production build passed (existing >500 KB chunk warning); `git diff --check` passed with Git line-ending normalization warnings only. No live package uninstall was run. Mocked tests and server integration tests do not prove a real WinGet uninstaller, interactive installer behavior, service ACL behavior, or PostgreSQL migration execution. Next recommended work is a controlled endpoint pilot for software and RDP before broader enablement.

## Direct WinGet search and installation (2026-11-07)

The active dashboard WinGet workflow searches the server's fixed `winget` community source, shows exact IDs and versions, retrieves exact package publisher/details on selection, selects one or more approved/enabled enrolled devices and machine/user scope, confirms, and submits the existing individual jobs. The device Software tab provides this install flow for its current device, plus approved Chocolatey packages and recent device job state. Each target still gets one independent job through the existing API. Successful installs request fresh device inventory scans.

The search and package-detail endpoints are available to LAB_ADMIN+; job submission requires LAB_ADMIN+ with CSRF. The server restricts direct requests to package-manager WINGET/source `winget`, validates the package ID, rechecks it with exact WinGet `show --id`, verifies any selected version against repository metadata, validates the target device/scope, and stores an audited job before delivery. Offline devices remain PENDING and existing expiry/redelivery/lifecycle handling applies. No arbitrary URL, executable, shell text or command arguments are accepted. The existing agent resolver, LocalSystem Session 0 machine-scope enforcement, foreground-only user-scope behavior, fixed arguments, timeouts, output bounds, durable journal and fresh-inventory installation verification are unchanged.

Direct WinGet jobs store `catalog_package_id=NULL`. Existing catalog rows and migrations 0005/0006 remain readable; no migration was needed because the job catalog foreign key is already nullable. Legacy catalog endpoints remain for compatibility and existing Chocolatey catalog jobs continue using the same approved-record flow and unchanged Chocolatey adapter. Installed Software uninstall now derives the exact package manager/ID/scope from the present inventory row and does not require a catalog approval; unsupported registry-only and ambiguous identities remain unavailable. WinGet and Chocolatey still run only through their fixed adapters, and registry uninstall strings are never executed.

Regression coverage was added for exact metadata parsing/version validation, fixed-source search authorization, direct audited/offline job creation without catalog approval, malformed or mismatched package IDs, source/scope/role rejection, catalog-independent uninstall, direct deployment confirmation/device selection, and existing Chocolatey and inventory verification paths. Verification: client **55 passed**; server **53 passed** with one existing Starlette/httpx deprecation warning; dashboard **23 passed** across 8 files; dashboard typecheck passed; production build passed with the existing >500 KB chunk warning; `git diff --check` passed with line-ending normalization warnings only. No migration was added or applied. Live WinGet installation under the actual LocalSystem service identity, real Chocolatey install/uninstall, and PostgreSQL validation remain host-level checks.

## Device dashboard software installation (2026-11-07)

The device details Software tab now includes individual WinGet search and install bound to the open device, verified package details, machine/user scope selection, approved Chocolatey installation, and recent job progress. Install authorization and execution still use the existing authenticated server endpoint, audited durable job, and fixed package-manager adapters. The installer is shown only to LAB_ADMIN users. A verified successful install requests inventory refresh. A regression test confirms the install targets the current device. Verification: dashboard **24 passed** across 8 files; typecheck passed; production build passed with the existing >500 KB chunk warning; `git diff --check` passed with Git line-ending normalization warnings only.

## Bulk software targeting (2026-11-07)

The `/deployment` confirmation supports selecting multiple enabled/approved PCs or selecting a room to target all its enabled/approved assigned devices. It submits the existing audited one-device job sequentially for each selected target, continues after per-device failures, reports queued/failed counts and device-specific errors, and leaves each persisted job visible in the existing monitor. Successful jobs trigger inventory refresh for their devices. Chocolatey continues through approved catalog jobs and its existing adapter. No aggregate deployment table/API or migration was introduced; reporting and retry remain per device/job.

Regression tests cover multi-PC submissions and whole-room target expansion. Dashboard tests: **26 passed** across 8 files; typecheck passed; production build passed with the existing >500 KB chunk warning; final `git diff --check` passed with Git line-ending normalization warnings only.

## Managed Remote Desktop access (2026-11-07)

The device Remote Access tab lets LAB_ADMIN users request RDP preparation from an online, enabled, approved endpoint. Migration 0008 persists and audits each request; migration 0009 stores the automatically detected active-console username returned over the authenticated WSS result. The client also reports hostname and username in system telemetry, and Device information displays them together. No endpoint username configuration is required. The dashboard prefills the detected username in the downloaded `.rdp` file; if no interactive console account is active or readable, it omits the username. The target reports READY or a bounded failure code. Requests expire after two minutes if the agent does not accept them. The client requires Windows and an elevated/LocalSystem token, rejects Windows Home and policy-disabled RDP, leaves Network Level Authentication unchanged, preserves prior `fDenyTSConnections` and `LimitBlankPasswordUse` values, temporarily permits blank-password local-account network logons, and adds TCP/3389 firewall rules restricted to local subnet on Domain/Private profiles. The agent restores both registry values and removes only its rules after 60 minutes, after service restart, or during normal agent shutdown. A later LAB_ADMIN request extends an active lease.

After readiness, the dashboard shows the automatically detected active console account and downloads a minimal `.rdp` file with that username prefilled to the current admin browser PC. If no active console username is available, the file omits it. Opening the file locally starts Windows Remote Desktop, which prompts for the password; credentials are never sent to or stored in LabGuard. Browser restrictions prevent a web page from silently launching local desktop apps. The admin PC needs a direct network route to the target; the LabGuard server does not proxy RDP traffic. See Microsoft's [Remote Desktop host requirements](https://learn.microsoft.com/en-in/windows-server/remote/remote-desktop-services/remotepc/remote-desktop-allow-access) and [`mstsc` connection file documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mstsc).

Regression coverage includes temporary registry/firewall setup and restoration, policy/edition/elevation rejection, fixed `netsh` arguments, server RBAC/audit/device binding/sequence checks, automatic username reporting/storage, Device information display, and admin-PC RDP file generation. Latest full suites: client **66 passed**; server **59 passed** with one existing Starlette/httpx deprecation warning; dashboard **29 passed**. Dashboard typecheck/build and `git diff --check` passed. PostgreSQL migration 0008 and actual Windows endpoint/connection/firewall/active-session detection/timeout validation remain deployment checks.

## Authorized process inspection and termination (2026-11-07)

The device Processes tab uses LAB_ADMIN-only, CSRF-protected request APIs and the existing ticket-authenticated WebSocket. Migration 0010 stores and audits `LIST`, `TERMINATE`, and `KILL` requests/results. The client reports up to 1,000 processes in bounded WSS batches with PID, name, username, CPU, memory, executable path, and microsecond creation time. Username/path values can be unavailable when Windows denies access. The UI polls persisted request state, displays process details, confirms termination actions, and refreshes after an action.

Termination targets must include both PID and creation time. The client rechecks that identity immediately before terminating, rejects PID reuse, and protects the agent and core Windows PIDs/processes. Process details are available only to LAB_ADMIN+; administrative requests and endpoint outcomes are audit events. No command strings, executable arguments, or shell execution are accepted. On Windows, psutil documents `terminate()` as an alias of `kill()` implemented with `TerminateProcess`; this action cannot promise an app-level save/close prompt. The separate Force Kill control is explicit and confirmed, but Windows uses the same process termination mechanism. See [psutil process termination behavior](https://psutil.readthedocs.io/stable/index.html).

Regression tests cover PID reuse, protected process refusal, and separate terminate/kill requests. Verification: client suite **66 passed**; server suite **59 passed** with one existing Starlette/httpx deprecation warning; dashboard suite **29 passed**; dashboard typecheck and production build passed (the existing >500 KB chunk warning remains); Python syntax checks and `git diff --check` passed. Dashboard coverage was updated for the existing HTTP/HTTPS compatibility behavior and RDP handoff wording. Migration 0010 and live Windows enumeration/termination were not exercised against PostgreSQL or a Windows endpoint and still require deployment validation.
