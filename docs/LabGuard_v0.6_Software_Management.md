# LabGuard v0.6 Software Management

## Review and deployment flow

1. Apply `alembic upgrade head` to create the approved package catalog, explicit review status, and persistent job tables. The current head is `0006_catalog_review_status`.
2. Set `CHOCOLATEY_SOURCE_URL` only when a managed HTTPS Chocolatey feed is configured. The URL may not contain credentials, a query, or a fragment. WinGet uses the `winget` community source.
3. Sign in as Super Admin, open **Software Deployment**, and add an exact WinGet or configured Chocolatey package identifier with publisher/description, version policy, and supported scope. Review the metadata and explicitly approve or reject the entry. Rejected entries remain visible for review but are hidden from device install choices. Chocolatey is machine-scope only.
4. Open an approved device's Software tab, search the approved catalog, select Install, review scope/version and device identity, then confirm. Uninstall is available only for a present WinGet/Chocolatey inventory entry whose exact package ID matches an approved catalog entry. Registry-only entries are unsupported.
5. Monitor the job from the same device Software tab. An offline device retains the job as PENDING until reconnect or expiry. Job results are persistent and audit-linked.

## Execution context

Machine operations require an elevated administrator or LocalSystem context. User-scope WinGet operations are available only in a foreground interactive user's process. All Session 0 service processes, including LocalSystem and custom service accounts, reject user-scope jobs; LabGuard does not impersonate a logged-in user, switch service accounts, or launch hidden interactive processes. Chocolatey user scope is unsupported. Missing package managers fail the job without affecting heartbeats.

The agent invokes fixed package-manager arguments with no shell, fixed WinGet/Chocolatey sources, strict package IDs, bounded execution time and bounded sanitized output. It then sends a full inventory scan. The server reports success only after the refreshed inventory confirms installation or removal. Chocolatey package uninstall scripts determine whether the underlying native application is removed; a Chocolatey exit code alone is never considered success. An uncertain interrupted execution is not automatically repeated; inspect inventory and create a new job if needed.

## Inventory diagnostics and status

WinGet inventory discovery checks the current process PATH and that execution identity's `LOCALAPPDATA\\Microsoft\\WindowsApps\\winget.exe` alias. Failures are distinguished in the agent log and inventory warnings: executable missing, access denied, timeout, App Installer/package registration, command failure, or unusable output. Logs do not dump environment values or command output. A registry scan remains available when WinGet cannot run. The interactive Krypton report has not been reproduced under the Windows Service identity, so the deployment-specific cause still needs confirmation from the client diagnostic logs.

Registry architecture is not inferred from the 32-bit or 64-bit registry view. An explicit `Architecture` registry value is normalized; absent values are `UNKNOWN`. Identical entries repeated in both views are deduplicated; different install locations or explicit architectures remain separate. A version update refreshes the same entry. Original registry view does not imply application architecture.

Collection status exposes the latest attempt, the latest successful collection (COMPLETE, UNCHANGED, or PARTIAL), and the latest complete collection (COMPLETE or UNCHANGED). PARTIAL indicates usable inventory plus warnings and is fresh until its successful timestamp crosses the stale threshold. Failed attempts do not erase the previously successful snapshot. PARTIAL snapshots do not mark unseen applications as removed.

## Verification

Automated tests mock package-manager processes and never install or remove software. Current verification: server **33 passed**, client **29 passed**, dashboard **12 passed**, dashboard typecheck passed, and production build passed with the existing >500 kB bundle warning. SQLite migration head 0006 upgrade/downgrade/upgrade is exercised by the server suite. PostgreSQL migration behavior should be checked against a disposable PostgreSQL database before production rollout. On a disposable Windows device, verify separately under the foreground account and the Windows Service LocalSystem context: package manager discovery and diagnostic reason, machine installation/removal, USER-scope rejection under LocalSystem, progress/result reporting, inventory confirmation, timeout, and reconnect behavior.
