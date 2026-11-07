# LabGuard Server

FastAPI management server for the LabGuard Windows lab fleet. This project is independent from labguard-client.

## Requirements

- Python 3.12 or newer (use the institution's approved supported runtime)
- PostgreSQL 14 or newer
- A unique random session secret of at least 32 characters

## Local setup (PowerShell)

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
Copy-Item .env.example .env
~~~

Edit .env with the PostgreSQL connection URL, a generated SESSION_SECRET, and SESSION_COOKIE_SECURE=false for local HTTP development only. In production, keep secure cookies enabled and terminate TLS in the trusted deployment layer. Do not commit .env.

Device liveness defaults to a 10-second application heartbeat, DELAYED after 30 seconds, and OFFLINE after 60 seconds. Adjust HEARTBEAT_INTERVAL_SECONDS, DEVICE_DELAYED_AFTER_SECONDS, and DEVICE_OFFLINE_AFTER_SECONDS together; startup validates their ordering. Device proof challenges and one-use WebSocket tickets default to 30 seconds each.
System telemetry is collected every 30 seconds by default over the existing authenticated WSS session as a typed `client.telemetry` event. The server keeps a current snapshot and compact history samples. Configure retention with `TELEMETRY_RETENTION_DAYS` (30 days), stale reporting with `TELEMETRY_STALE_AFTER_SECONDS` (120 seconds), and the ingestion floor with `TELEMETRY_MIN_INTERVAL_SECONDS` (10 seconds). Apply all migrations through head before starting.

Software inventory uses the same authenticated WSS session with typed, bounded `client.software_inventory` batches. Migration 0004 creates per-device collection history, batch receipts, and current/historical software entries; migration 0007 stores source provenance for reconciled entries. Complete scans mark previously present entries absent; partial scans never do. Absence means “not observed in a later complete scan,” not a confirmed uninstall. Inventory older than seven days is stale by default. Configure `SOFTWARE_INVENTORY_STALE_AFTER_SECONDS`, manual refresh cooldown with `SOFTWARE_INVENTORY_REFRESH_COOLDOWN_SECONDS` (300 seconds), collection ingest minimum interval with `SOFTWARE_INVENTORY_MIN_INTERVAL_SECONDS` (10 seconds, max 60), and collection history retention with `SOFTWARE_INVENTORY_RETENTION_DAYS` (90 days). Rate-limited client reports receive a retry delay and the agent retries once without blocking heartbeat traffic.

Create the database and a least-privilege PostgreSQL user using your site's PostgreSQL administration process. Then apply migrations:

~~~powershell
alembic upgrade head
~~~

Create the first administrator interactively (password is prompted and hashed with Argon2id):

~~~powershell
python -m labguard_server.cli create-admin --username lab-admin --role SUPER_ADMIN
~~~

Start the server locally with `Start-LabGuard-Server.bat` from the repository root. It defaults to `127.0.0.1:8000`. Set `LABGUARD_HOST=0.0.0.0` and `LABGUARD_PORT=8000` in the launching shell for LAN testing. See `../docs/LabGuard_LAN_Deployment.md` for client, dashboard, firewall and TLS setup.

The API is versioned under /api/v1. Liveness and readiness are /api/v1/health/live and /api/v1/health/ready. Interactive API docs should be disabled or access-restricted at the production ingress; this initial foundation does not yet implement an authenticated OpenAPI UI policy.

LAB_ADMIN and SUPER_ADMIN may permanently remove a device with `DELETE /api/v1/devices/{device_id}` using the administrator session cookie and `X-CSRF-Token`. The server revokes its credential and writes a `device.delete` audit snapshot in the deletion transaction, cascades device-owned records and room assignments, closes the active agent socket, and publishes a `device.deleted` SSE invalidation. Audit events remain queryable after device removal. A deleted device must enroll and be approved again to reconnect.

After admin approval, each device has an active Ed25519 public-key credential. The client obtains POST /api/v1/agent/challenge, signs the canonical UTF-8 message `labguard.device.auth.v1\\n{device_uuid}\\n{challenge_uuid}\\n{sha256_hex(nonce)}`, and exchanges it at POST /api/v1/agent/ticket. The returned random ticket is short lived and single use, sent in the WSS Authorization header (never in the URL). The connection requires client.hello first, then accepts client.heartbeat and client.telemetry with correlated acknowledgements. Telemetry is associated with the device authenticated by its ticket and does not update heartbeat status or administrative device fields. Viewer-authenticated reads are GET /api/v1/devices/{id}/telemetry, GET /api/v1/devices/{id}/telemetry/history, and GET /api/v1/telemetry/summary. Device status and last seen are server receipt time; a dropped connection becomes OFFLINE only after the configured heartbeat timeout. A Super Admin can revoke a device credential at POST /api/v1/devices/{id}/credential/revoke.

Software inventory adds `client.software_inventory` to that same WSS envelope; the payload carries protocol inventory version 1, collection UUID/time, batch index/count, status, digest, bounded error codes, and at most 100 normalized entries. The server derives device identity only from the authenticated ticket. Each batch receives an acknowledgement; the dashboard receives a metrics-free `software.inventory` SSE invalidation after a complete collection. Manual refresh uses `server.software_inventory.refresh` with a server-generated request UUID matched to its pending server-side request. Viewer+ roles can read GET `/api/v1/devices/{id}/software`, `/api/v1/software`, `/api/v1/software/summary`, and `/api/v1/software/{software_key}/installations`; LAB_ADMIN+ with CSRF can POST `/api/v1/devices/{id}/software/refresh`.

Individual software jobs are persisted and delivered over the authenticated WSS session using `server.software_job.offer` and client lifecycle events; the dashboard receives `software.job` invalidations. LAB_ADMIN+ can search the fixed WinGet community repository and submit direct exact-ID installs with an optional repository-verified version and supported scope. The server rechecks package metadata and persists/audits the job without creating a catalog row. This remains one device per job; offline devices remain pending until delivery or expiry. Existing catalog records and migrations 0005/0006 remain readable for compatibility, and existing approved Chocolatey jobs continue unchanged. Migration 0007 stores inventory source provenance. Set `CHOCOLATEY_SOURCE_URL` to a configured HTTPS feed to enable Chocolatey jobs. `SOFTWARE_JOB_MAX_RUNTIME_SECONDS` defaults to 1800 and is bounded from 60 to 7200. Uninstall requires a present inventory row with an exact supported identity/scope and no longer requires catalog approval. The agent never accepts arbitrary executable paths, download URLs, shell commands, or registry uninstall strings. See `../docs/LabGuard_Development_State.md` for execution restrictions and manual verification.

## Migrations

Schema changes must be represented by Alembic revisions. Apply with alembic upgrade head; inspect and back up the database before production migrations. The initial revision is migrations/versions/0001_initial.py. The app never creates schema automatically at startup.

## Tests

~~~powershell
python -m pytest
~~~

The integration fixture uses SQLite and applies all Alembic migrations. The test suite exercises upgrade, downgrade to 0004, and upgrade again through migration 0007. Client tests are in `../labguard-client/tests`; use its test extra to run them. PostgreSQL verification is environment-specific and has not been performed for migration 0007; use a disposable database before applying migrations to any shared environment.

The WSS integration test launches a local Uvicorn server and two real AgentClient instances. For local plaintext HTTP only, the client requires the explicit `allow_insecure_dev=True` option or CLI `--insecure-dev` flag.

## MVP notes

Administrator sessions are opaque, stored as hashes, expiring and revocable. Mutating browser requests require X-CSRF-Token. Roles are VIEWER, OPERATOR, LAB_ADMIN, SUPER_ADMIN. Enrollment requests consume one-use admin-created codes and stay pending until approval. Approved Ed25519 credentials authenticate one-use WSS tickets; revocation closes active sessions and quarantines the device. Grid coordinates are zero-based, unique per room, bounded by configured dimensions, and readable/editable through the room layout API. Administrative changes are written to audit_events in the same transaction.
