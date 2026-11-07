# LabGuard Dashboard

Independent React, Vite, TypeScript and Tailwind administrator dashboard for the existing LabGuard API. It reads the current server contract; unsupported capabilities are labeled in the UI rather than simulated.

## Requirements

- Node.js 20.19+ (or 22.12+) and npm
- LabGuard server running at `http://127.0.0.1:8000`
- Administrator account created with the server CLI

## Local development (PowerShell)

From `labguard-server`, start the API:

~~~powershell
uvicorn labguard_server.main:app --env-file .env --host 127.0.0.1 --port 8000
~~~

In another terminal:

~~~powershell
cd labguard-dashboard
npm install
npm run dev
~~~

Open the Vite URL printed by npm. Vite proxies `/api` to the local server, so the browser session cookie remains same-origin. For a deployed same-origin setup, leave `VITE_API_BASE_URL` unset. If the dashboard is hosted on a different origin, the server needs an explicit credentialed CORS and cookie deployment policy; this project does not bypass it.

## Checks and production build

~~~powershell
npm test
npm run typecheck
npm run build
npm run preview
~~~

## Current integration

- `POST /api/v1/auth/login`, `GET /auth/me`, `POST /auth/logout` with the server-managed HttpOnly cookie and CSRF token returned at login. CSRF token is kept only in tab-scoped `sessionStorage` so reloads in that tab retain mutation support; passwords and cookie secrets are never stored by JavaScript.
- `GET /devices` and `GET /devices/{id}/status` for fleet list, profile, overview counts, connection state, and event-driven status refresh.
- `GET /devices/{id}/telemetry`, `GET /devices/{id}/telemetry/history`, and `GET /telemetry/summary` for the current system snapshot, bounded history, and live fleet aggregates.
- `DELETE /devices/{id}` for permanent device removal. LAB_ADMIN and SUPER_ADMIN see a confirmation with the device identity; the server performs the authoritative role/CSRF checks and emits a `device.deleted` event so connected dashboards refresh device, room, status, telemetry, and audit data.
- `GET /rooms`, `POST /rooms`, `PATCH /rooms/{id}` for room list and authorized room dimension/name/description editing.
- `GET /enrollment/requests`, approval/rejection endpoints, and `POST /enrollment-codes` for Lab Admin and above.
- `GET /audit-events?limit=25` for audit activity.

The dashboard receives authenticated status and connection events from the separate administrator Server-Sent Events endpoint `/api/v1/admin/events`; the device WebSocket at `/api/v1/agent/session` remains restricted to device tickets. EventSource reconnects after a dropped stream and invalidates inventory queries after `software.inventory` and job queries after `software.job`. Room assignments can be read and saved through `/api/v1/rooms/{id}/layout`; the dashboard provides an editor for approved devices and grid positions.

- `GET /software`, `GET /software/summary`, and `GET /software/{software_key}/installations` power the searchable global inventory page, aggregate cards, and application installation drawer.
- `GET /devices/{id}/software` powers the device Software tab, including collection freshness, source, scope, version, and publisher. LAB_ADMIN+ can request an immediate full scan with `POST /devices/{id}/software/refresh`; server-side role and CSRF checks remain authoritative.
- `/deployment` searches the fixed WinGet community source, verifies exact package details, selects individual PCs or all eligible devices assigned to a room, confirms installation, and monitors each persisted per-device job. Successful installs request fresh inventory scans. Installed Software remains the place to inspect and safely uninstall present applications.
- Device details' Remote Access tab lets LAB_ADMIN+ request a temporary 60-minute RDP lease and download a minimal `.rdp` file on the current admin PC. Opening the file locally starts Windows Remote Desktop; the browser cannot launch local desktop applications itself. Windows still prompts for target credentials, and the admin PC needs direct network reachability to the endpoint.

Software inventory, deployment, and RDP readiness use actual server/agent data. Process and USB pages remain unavailable because those APIs are not implemented. Device details show current telemetry, metric history, storage, interfaces, installed software, per-device jobs, and RDP request state; the overview shows fleet telemetry aggregates. See `../docs/LabGuard_LAN_Deployment.md` for local, LAN and production preparation guidance and `../docs/LabGuard_Development_State.md` for the current handoff and remaining manual checks.
