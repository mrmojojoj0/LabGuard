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
npm run typecheck
npm run build
npm run preview
~~~

## Current integration

- `POST /api/v1/auth/login`, `GET /auth/me`, `POST /auth/logout` with the server-managed HttpOnly cookie and CSRF token returned at login. CSRF token is kept only in tab-scoped `sessionStorage` so reloads in that tab retain mutation support; passwords and cookie secrets are never stored by JavaScript.
- `GET /devices` and `GET /devices/{id}/status` for fleet list, profile, overview counts, and 20-second status polling.
- `GET /rooms`, `POST /rooms`, `PATCH /rooms/{id}` for room list and authorized room dimension/name/description editing.
- `GET /enrollment/requests`, approval/rejection endpoints, and `POST /enrollment-codes` for Lab Admin and above.
- `GET /audit-events?limit=25` for audit activity.

The API has no pagination/filter parameters for devices, no room-layout read endpoint, no device telemetry/interfaces/inventory endpoints, no status history endpoint, and no administrator event-stream WebSocket. The device WebSocket at `/api/v1/agent/session` only accepts one-use device tickets and agent protocol messages; the dashboard never connects to it. Software/process/network/USB/remote access pages and non-overview detail tabs are marked as planned/unavailable.

Room dimension changes are supported, but placements cannot be loaded or safely edited through the current API response. The room grid preview therefore shows dimensions only and does not invent placements.
