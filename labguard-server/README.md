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

Create the database and a least-privilege PostgreSQL user using your site's PostgreSQL administration process. Then apply migrations:

~~~powershell
alembic upgrade head
~~~

Create the first administrator interactively (password is prompted and hashed with Argon2id):

~~~powershell
python -m labguard_server.cli create-admin --username lab-admin --role SUPER_ADMIN
~~~

Start the server:

~~~powershell
uvicorn labguard_server.main:app --env-file .env --host 127.0.0.1 --port 8000
~~~

The API is versioned under /api/v1. Liveness and readiness are /api/v1/health/live and /api/v1/health/ready. Interactive API docs should be disabled or access-restricted at the production ingress; this initial foundation does not yet implement an authenticated OpenAPI UI policy.

After admin approval, each device has an active Ed25519 public-key credential. The client obtains POST /api/v1/agent/challenge, signs the canonical UTF-8 message `labguard.device.auth.v1\\n{device_uuid}\\n{challenge_uuid}\\n{sha256_hex(nonce)}`, and exchanges it at POST /api/v1/agent/ticket. The returned random ticket is short lived and single use, sent in the WSS Authorization header (never in the URL). The connection requires client.hello first, then accepts client.heartbeat and returns acknowledgements. Device status and last seen are server receipt time; a dropped connection becomes OFFLINE only after the configured heartbeat timeout. A Super Admin can revoke a device credential at POST /api/v1/devices/{id}/credential/revoke.

## Migrations

Schema changes must be represented by Alembic revisions. Apply with alembic upgrade head; inspect and back up the database before production migrations. The initial revision is migrations/versions/0001_initial.py. The app never creates schema automatically at startup.

## Tests

~~~powershell
python -m pytest
~~~

The integration fixture uses SQLite and applies the Alembic migration. Production uses PostgreSQL. Run migration and deployment checks against a disposable PostgreSQL instance before release.

The WSS integration test launches a local Uvicorn server and two real AgentClient instances. For local plaintext HTTP only, the client requires the explicit `allow_insecure_dev=True` option or CLI `--insecure-dev` flag.

## MVP notes

Administrator sessions are opaque, stored as hashes, expiring and revocable. Mutating browser requests require X-CSRF-Token. Roles are VIEWER, OPERATOR, LAB_ADMIN, SUPER_ADMIN. Enrollment requests consume one-use admin-created codes and stay pending until approval. Client public keys are recorded for the phase 1 registry; device credential issuance and authenticated WSS are a later milestone. Grid coordinates are zero-based, unique per room, and bounded by configured dimensions. Administrative changes are written to audit_events in the same transaction.
