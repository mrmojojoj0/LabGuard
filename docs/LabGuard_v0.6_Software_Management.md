# LabGuard v0.6 Software Management

## Review and deployment flow

1. Apply `alembic upgrade head` to create the approved package catalog and persistent job tables.
2. Set `CHOCOLATEY_SOURCE_URL` only when a managed HTTPS Chocolatey feed is configured. The URL may not contain credentials, a query, or a fragment. WinGet uses the `winget` community source.
3. Sign in as Super Admin, open **Software Inventory**, and add an exact package identifier with publisher/description, version policy, and supported scope. Review and approve the catalog entry. Chocolatey is machine-scope only.
4. Open an approved device's Software tab, search the approved catalog, select Install, review scope/version and device identity, then confirm. Uninstall is available only for a present WinGet/Chocolatey inventory entry whose exact package ID matches an approved catalog entry. Registry-only entries are unsupported.
5. Monitor the job from the same device Software tab. An offline device retains the job as PENDING until reconnect or expiry. Job results are persistent and audit-linked.

## Execution context

Machine operations require an elevated administrator or LocalSystem context. User-scope WinGet operations are available only in a foreground interactive user's process. All Session 0 service processes, including LocalSystem and custom service accounts, reject user-scope jobs; LabGuard does not impersonate a logged-in user, switch service accounts, or launch hidden interactive processes. Chocolatey user scope is unsupported. Missing package managers fail the job without affecting heartbeats.

The agent invokes fixed package-manager arguments with no shell, fixed WinGet/Chocolatey sources, strict package IDs, bounded execution time and bounded sanitized output. It then sends a full inventory scan. The server reports success only after the refreshed inventory confirms installation or removal. Chocolatey package uninstall scripts determine whether the underlying native application is removed; a Chocolatey exit code alone is never considered success. An uncertain interrupted execution is not automatically repeated; inspect inventory and create a new job if needed.

## Verification

Automated tests mock package-manager processes and never install or remove software. Run server, client and dashboard tests plus dashboard typecheck/build. SQLite migrations are exercised by the server integration fixture. PostgreSQL migration behavior should be checked against a disposable PostgreSQL database before production rollout. On a disposable Windows device, verify separately under the foreground account and the Windows Service LocalSystem context: package manager discovery, machine installation/removal, USER-scope rejection under LocalSystem, progress/result reporting, inventory confirmation, timeout, and reconnect behavior.
