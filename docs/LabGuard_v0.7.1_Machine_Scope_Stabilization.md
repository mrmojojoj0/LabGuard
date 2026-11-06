# LabGuard v0.7.1 — Machine-Scope Installation Stabilization

Date: 2026-11-07
Status: Code and mocked regression coverage implemented; live Windows endpoint verification remains pending.

## Findings

Software job flow remains on the existing path: the server persists and audits an approved `SoftwareJob`, dispatches `server.software_job.offer` over the authenticated device WebSocket, and the client validates and journals it before running the package adapter. The client reports accepted/started/progress/terminal events on that session. After manager success it performs a fresh inventory scan and reports success only when inventory verifies the requested state.

The process that runs WinGet is the Python client process receiving the WebSocket offer. When installed through the existing Windows Service flow, that process is `LabGuardWindowsService` in Session 0. The service installer does not specify an account; pywin32's `InstallService` default is LocalSystem. The service path keeps its existing machine-DPAPI identity and authenticated connection.

The concrete code defect was `is_administrator()` having no Windows implementation (it returned `None`). The intended `IsUserAnAdmin` code was unreachable after `running_in_service_session` had already returned. Thus a foreground administrator token was misdetected as unprivileged. In addition, the previous policy allowed any foreground administrator to execute a MACHINE job, contrary to the requirement that machine-scope operations run through the privileged service.

This development host has no installed `LabGuardAgent` service. The account and token of a deployed service therefore could not be read directly here. Runtime startup logging now records the actual process account, LocalSystem SID match, elevation state and Session 0 state on the endpoint.

## Changes

- Compare the current Windows token SID with the LocalSystem well-known SID instead of comparing account-name strings.
- Implement `TokenElevation` inspection and fail closed when the token cannot be queried.
- Restrict WinGet MACHINE jobs to the LocalSystem process in Session 0. Foreground delivery returns `privileged_service_unavailable`; a non-elevated Session 0 process returns `machine_scope_requires_administrator`.
- Use the existing safe client discovery to find the machine-registered App Installer package under Program Files as well as the current account's WindowsApps alias.
- Preserve USER-scope execution in a foreground interactive agent. A Session 0 service returns `user_scope_unavailable_in_service_session`; no user impersonation or hidden helper is introduced.
- Map package process creation access denial to `machine_scope_permission_denied` or `user_scope_permission_denied`.
- Log service identity context at startup. Existing job authentication, journal/idempotency, lifecycle reporting, audit persistence and post-operation inventory verification remain in place.
- Chocolatey package parsing, command building, service behavior and execution are unchanged.

## Verification

- Client automated suite: 32 passed (`labguard-client/.venv/Scripts/python.exe -m pytest -q`). Tests use mocked WinGet executables. New coverage checks token elevation/access-denied handling, privileged-service unavailability, interactive USER scope, process permission errors, and machine App Installer path discovery.
- A real Firefox MACHINE install, a real USER install, fresh endpoint inventory verification, and service stopped/unavailable behavior were not run: this checkout host has no `LabGuardAgent` service and no designated disposable Windows test endpoint. The automated suite cannot establish real App Installer registration, service-token WinGet access, package behavior, or Windows inventory visibility.
- Server and dashboard code were not changed for this client-side execution-context fix. Server tests, dashboard tests, typecheck and production build were not rerun for this change.

## Next steps

1. On a designated disposable Windows endpoint, inspect the service startup log for LocalSystem, elevated token and Session 0.
2. Send an approved Firefox MACHINE job through LabGuard; confirm `verified_success` only after the fresh inventory scan includes Mozilla Firefox.
3. Run an approved USER job from a foreground interactive agent and confirm that a service-delivered USER job fails with the explicit Session 0 error.
4. Stop/remove the service in the test environment and verify the machine job reports `privileged_service_unavailable`; test access-denied behavior without changing the service account on production systems.
5. If service-originated USER jobs are required, authorize a separate design for a user-visible interactive broker with authenticated, narrowly scoped local IPC and explicit session selection. Do not add arbitrary command or account-switching mechanisms.

v0.8 and bulk deployment were not started.
