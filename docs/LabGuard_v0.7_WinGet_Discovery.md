# LabGuard v0.7 — Central WinGet Discovery and Catalog Integration

## Scope

v0.7 adds server-side search of configured WinGet sources and routes selected packages into the existing software catalog review and individual deployment workflow. It does not replace client inventory collection or the existing authenticated agent job system.

## Discovery and review flow

1. The Super Admin deployment page reads WinGet status, including the version and identity under which the server process runs, and lists configured WinGet source names.
2. The administrator searches a selected source. The server runs WinGet locally using bounded subprocess calls and argument arrays, then parses the aligned terminal table output. Single-source search results often omit the Source column, so the parser applies the selected source name. Search results are capped at 100. It does not rely on an undocumented JSON option.
3. A selected result from the winget source can be imported. The server performs an exact show --id ... --exact lookup for the package name, publisher, and description, then creates a PENDING WINGET catalog entry.
4. The existing Super Admin approval/rejection controls govern whether the package becomes available for deployment. Existing device software controls create the same persisted single-device jobs as before.
5. Each client continues discovering its own installed applications and executes any approved WinGet operation locally. The server never performs a client's installation or uninstall.

The device Software page keeps its existing Search approved packages field, which calls the approved catalog endpoint. Super Admins also have a separate Search WinGet Repository form on that page. Typing in either field does not trigger the other search; only submitting the repository form calls live server-side discovery. The deployment page retains its own repository search form as well.

## API and safety

- GET /api/v1/software/discovery/status reports availability, version, current execution identity, and a structured failure reason.
- GET /api/v1/software/discovery/sources lists configured source names without exposing source addresses.
- GET /api/v1/software/discovery/search?query=...&source=... returns repository matches and current catalog review state. The dashboard calls it only from the explicit Search WinGet Repository action; the approved catalog text field still calls GET /api/v1/software/catalog.
- POST /api/v1/software/discovery/import requires Super Admin plus CSRF, validates package IDs/source/scope, retrieves exact package metadata, deduplicates case-insensitively, and audits new pending entries.
- Discovery subprocesses use argument lists, shell=False, a 60-second timeout, bounded query/source/identifier input, and sanitized structured errors. There is no administrator-supplied command, executable path, or URL.
- Existing client execution only accepts its established winget community source. Other configured sources can be searched, but their results cannot be imported into the deployable catalog until the client execution contract supports those sources.
- No database migration or WebSocket/client protocol change was needed. Chocolatey code, tests, configuration, and behavior were left unchanged.

## Verification and limits

- Server: pytest -q — 43 passed, one existing Starlette/httpx deprecation warning.
- Dashboard: npm test -- --run — 16 passed; npm run typecheck passed; npm run build passed with the existing >500 kB JavaScript chunk warning.
- WinGet subprocesses are mocked in tests. A live search under the deployed Windows server identity and PostgreSQL behavior were not verified in this environment.
- v0.8 work was not started.