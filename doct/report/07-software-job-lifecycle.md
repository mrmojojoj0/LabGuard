# Software Job Lifecycle and Execution

## Design goal

Software management uses a durable server job, an authenticated delivery event, an endpoint idempotency journal, a constrained package adapter, and post-operation inventory verification. The implementation is for individual device operations. It does not provide a separate bulk deployment engine or arbitrary command runner.

## Request validation and persistence

1. A LAB_ADMIN submits a typed INSTALL or UNINSTALL request to `/devices/{device_id}/software/jobs` with CSRF protection.
2. The server validates target approval/enabled state, action, manager, exact package identity, scope, catalog authorization or inventory row, configured Chocolatey source, and any repository-verified WinGet version.
3. For direct WinGet INSTALL, the server performs an exact metadata lookup from the fixed `winget` source before job creation. Uninstall may target a safely identified installed inventory row without a catalog record.
4. The server creates a durable `SoftwareJob`, writes the audit event in the same transaction, and publishes a dashboard invalidation. The API returns accepted state; this is not completion.
5. Online jobs are offered over the authenticated device WebSocket. Offline jobs remain pending for later delivery.

## Delivery and endpoint algorithm

1. Agent receives `server.software_job.offer` on the authenticated socket and validates protocol version, job UUID, target identity, expiry, action, package manager/ID, scope and approved catalog metadata.
2. Before side effects, it writes/updates a durable local journal. Replayed terminal jobs return their saved result; uncertain RUNNING jobs are not blindly repeated after reconnect.
3. It reports accepted/started lifecycle events, then selects a narrow manager adapter. WinGet uses a discovered App Installer executable and fixed argument lists. Chocolatey uses its established configured executable/source and safe parsing. Both use `shell=False`, bounded runtime/output, and no arbitrary command text.
4. Execution context is enforced: MACHINE WinGet work requires the LocalSystem Session 0 service; USER scope runs only in a foreground interactive agent. The specific typed WinGet USER uninstall exception uses a narrowly scoped active-console helper that verifies the exact package under that user. It does not generalize to installs, other managers, or arbitrary user-session actions.
5. Progress and terminal results are sent through typed WebSocket messages. The server binds them to the authenticated device and updates the persisted job state.
6. After manager success, the client performs a fresh software inventory scan. Success is reported only when the requested installed/uninstalled state is verified; a zero exit code by itself is insufficient.

## Job states, retries and cancellation

The job record captures request, device, action, package identity/scope, status, timestamps and bounded result/error fields. The dashboard shows server-persisted state and does not fabricate progress. Redelivery is expected; local journal/idempotency rules prevent repeated effects. A job in an uncertain RUNNING state is treated conservatively. Terminal history can be cleared only through authorized, audited routes; active jobs are never deleted. The feature has bounded expiry, output and process runtime.

## Authorization pathways

Legacy catalog-driven jobs require an approved catalog entry; catalog review is Super Admin controlled. Direct WinGet installation is available to LAB_ADMIN+ after exact repository metadata validation. Job creation is CSRF protected. Server RBAC is decisive even when the dashboard hides controls. Package identity is exact and source selection is fixed for the supported WinGet execution path.

## Failure semantics and future expansion

The lifecycle distinguishes unavailable service context, missing manager, permission denial, manager failure, timeout, inventory verification failure, rejected/expired offer and agent disconnect. The server should not display an install as successful just because it queued or sent the offer. Bulk deployment, update workflows, arbitrary package sources and user impersonation are outside this implementation. A future fan-out design must persist authorized targets before dispatch and define atomicity, concurrency, retries and cancellation while reusing `SoftwareJob`.

## Source map

Server transitions and dispatch: `software_jobs.py` plus `websocket.py`; endpoint loops and journal: `agent.py`; manager operations: `software_management.py`; user-scope helper: `software_user_helper.py`; inventory verification: `software_inventory.py`; dashboard state/progress mapping: `src/features/software/jobProgress.ts`.
