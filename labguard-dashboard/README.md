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

The dashboard receives authenticated status and connection events from the separate administrator Server-Sent Events endpoint `/api/v1/admin/events`; the device WebSocket at `/api/v1/agent/session` remains restricted to device tickets. EventSource reconnects after a dropped stream. Room assignments can be read and saved through `/api/v1/rooms/{id}/layout`; the dashboard provides an editor for approved devices and grid positions.

Software/process/USB/remote access pages remain unavailable because those APIs are not implemented. Device details now show current telemetry, metric history, storage, and interfaces; the overview shows fleet telemetry aggregates. See `docs/LabGuard_LAN_Deployment.md` for local, LAN and production preparation guidance.
