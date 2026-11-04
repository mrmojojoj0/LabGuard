# LabGuard LAN deployment (development)

This guide covers local development and trusted-subnet LAN testing for the current single-server LabGuard architecture. It is not a production deployment recipe.

## Local development on one machine

1. Configure `labguard-server/.env` from `.env.example`; provide PostgreSQL `DATABASE_URL`, a random `SESSION_SECRET` of at least 32 characters, and `SESSION_COOKIE_SECURE=false` for local HTTP only.
2. In PowerShell from the repository root, start the server and dashboard separately:

   ```powershell
   .\Start-LabGuard-Server.bat
   .\Start-LabGuard-Dashboard.bat
   ```

3. Open the Vite address shown in its terminal, usually `http://127.0.0.1:5173`. Sign in, generate an eight-character, one-time enrollment code, and keep it available for the client.
4. Set the explicit local HTTP development opt-in, enroll, and wait for admin approval:

   ```powershell
   $env:LABGUARD_ALLOW_INSECURE_DEV = '1'
   .\Start-LabGuard-Client.bat enroll
   ```

   After approval, run `Start-LabGuard-Client.bat` without arguments.

## LAN testing: one server and multiple client PCs

Keep the server, dashboard, and agents on a trusted private network. Find the server machine's LAN address with `ipconfig`; do not put a machine-specific IP in the launchers.

On the server PC, set its bind address and start the API and dashboard:

```powershell
$env:LABGUARD_HOST = '0.0.0.0'
$env:LABGUARD_PORT = '8000'
.\Start-LabGuard-Server.bat
$env:LABGUARD_DASHBOARD_HOST = '0.0.0.0'
$env:LABGUARD_DASHBOARD_PORT = '5173'
$env:LABGUARD_API_PROXY_TARGET = 'http://127.0.0.1:8000'
.\Start-LabGuard-Dashboard.bat
```

Allow only private-profile, local-subnet traffic to the development ports. Run PowerShell as Administrator on the server PC:

```powershell
New-NetFirewallRule -DisplayName 'LabGuard development API' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName 'LabGuard development dashboard' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5173 -Profile Private -RemoteAddress LocalSubnet
```

Open `http://<server-lan-ip>:5173` from an admin PC, sign in, and generate an eight-character, one-time enrollment code. From each client PC, set the server URL to the address shown by `ipconfig`, then enroll with that code:

```powershell
$env:LABGUARD_SERVER_URL = 'http://<server-lan-ip>:8000'
$env:LABGUARD_ALLOW_INSECURE_DEV = '1'
.\Start-LabGuard-Client.bat enroll
```

After admin approval, start the agent with `.\Start-LabGuard-Client.bat`. The agent uses HTTPS/WSS with certificate verification by default. Plain HTTP/WS is accepted only when `LABGUARD_ALLOW_INSECURE_DEV=1` is explicitly set; do not use that mode on an untrusted network. A safer LAN setup uses HTTPS and WSS with a certificate whose name matches the server URL and whose issuing CA is trusted by each PC.

The dashboard's administrator event stream uses the authenticated session cookie over its same-origin `/api/v1/admin/events` endpoint. The device-agent WebSocket remains a separate protocol and is never used to authenticate administrators.

## Production preparation

Before production, terminate HTTPS/WSS at a trusted ingress using a valid, monitored certificate; keep `SESSION_COOKIE_SECURE=true`; use PostgreSQL with least-privilege credentials; bind the API behind the ingress; restrict firewall access to required sources and ports; use unique administrator credentials; back up PostgreSQL and test restore; define retention and privacy rules; and test service restart, certificate renewal, backup restore, and client reconnect on the deployment platform. The current app is a single instance and the admin event fan-out is in-process; multi-instance operation requires a shared event broker and is not implemented or verified.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `LABGUARD_HOST` | `127.0.0.1` | Uvicorn bind host; set `0.0.0.0` for LAN testing |
| `LABGUARD_PORT` | `8000` | Uvicorn port |
| `LABGUARD_DASHBOARD_HOST` | `127.0.0.1` | Vite bind host |
| `LABGUARD_DASHBOARD_PORT` | `5173` | Vite port |
| `LABGUARD_API_PROXY_TARGET` | `http://127.0.0.1:8000` | Dashboard's server-side API proxy target |
| `LABGUARD_SERVER_URL` | `http://127.0.0.1:8000` | Agent API/WebSocket base URL |
| `LABGUARD_ALLOW_INSECURE_DEV` | unset | Must be `1` to allow agent HTTP/WS development mode |
| `LABGUARD_STATE_DIR` | `%PROGRAMDATA%\LabGuard` | Agent identity directory |

For component install and admin bootstrap instructions, see each project's README.