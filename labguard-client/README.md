# LabGuard Client

Minimal Windows endpoint agent for authenticated device enrollment and heartbeat communication. It has no remote execution, software deployment, process control, packet capture, or USB monitoring functionality.

## Install

Use the institution-approved Python 3.12+ runtime. On Windows, install the Windows extra for DPAPI-backed private key storage:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[windows]"
~~~

The identity file is stored under `%PROGRAMDATA%\LabGuard\identity.json` by default. Foreground enrollment protects its Ed25519 private key with current-user DPAPI. Service preparation migrates that same key to machine-scope DPAPI so LocalSystem can decrypt it after reboot without an interactive logon. The service preparation command must run as the Windows account that enrolled the device; it never creates a missing identity. The state directory and its files are given a protected ACL for that account, LocalSystem, and Administrators. Do not copy identity state to another PC.

## Enrollment and run

An administrator must first create an eight-character, one-use enrollment code in the server. Submit a pending request:

~~~powershell
labguard-agent enroll --server https://labguard.example.edu --code <one-time-code>
~~~

For the repository launcher, set `LABGUARD_SERVER_URL` to the server base URL, then run `Start-LabGuard-Client.bat enroll`. After approval, run the launcher without arguments. HTTP requires explicit development opt-in by setting `LABGUARD_ALLOW_INSECURE_DEV=1`; keep certificate verification enabled for HTTPS/WSS. See `docs/LabGuard_LAN_Deployment.md` for LAN guidance.

After an administrator approves the pending UUID and assigns a name, start the agent:

~~~powershell
labguard-agent run --server https://labguard.example.edu
~~~

The agent verifies TLS using the operating system trust store, proves possession of its Ed25519 private key, obtains a short-lived one-use WebSocket ticket, sends hello, and sends application heartbeats at the server-provided interval. It collects CPU, memory, storage, Windows/OS, uptime, and network interface metadata immediately after authentication and every 30 seconds by default. Configure the foreground interval with `--telemetry-interval-seconds` or `LABGUARD_TELEMETRY_INTERVAL_SECONDS` (10–3600 seconds); for a service, supply the value to `service prepare`. Collection runs off the heartbeat loop, and collection or telemetry rejection errors do not stop heartbeat operation. The collector does not inspect user files or browsing information. It reconnects with capped exponential backoff and jitter. Plain HTTP is rejected unless `--insecure-dev` is explicitly set for local development.

## Windows Service

Install Python 3.12 for all users in a location readable by LocalSystem. Install the client as a normal package (not editable) so the service does not depend on a user profile or OneDrive working tree. Enroll this device and wait for an administrator to approve it. Open an elevated PowerShell session as the same Windows account that enrolled the device:

~~~powershell
$Client = (Resolve-Path .\labguard-client).Path
py -3.12 -m pip install "$($Client)[windows]"
py -3.12 -m labguard_client.cli service prepare --server https://labguard.example.edu
py -3.12 -m labguard_client.cli service install
py -3.12 -m labguard_client.cli service start
py -3.12 -m labguard_client.cli service status
~~~

`prepare` requires the existing `%PROGRAMDATA%\LabGuard\identity.json`; it migrates DPAPI protection from current-user scope to machine scope while retaining the UUID, key, and sequence. It writes only the HTTPS server URL and state path to `service.json`. TLS verification remains enabled. The service runs as LocalSystem, starts automatically with Windows, logs to `%PROGRAMDATA%\LabGuard\labguard-agent.log`, retries disconnected sessions, and stops by cancelling active async operations and closing the WebSocket. A cross-process lock beside the identity prevents a foreground process and service from using the same identity together.

Manage it with `py -3.12 -m labguard_client.cli service start|stop|restart|status|uninstall`. Uninstall retains the identity and configuration. Installation is idempotent. Service management requires an elevated prompt. Do not run the foreground agent while the service is active.

Windows Service runtime behavior, actual DPAPI machine-scope migration, ACL enforcement, and automatic startup require verification on Windows. Manual verification: enroll and approve a test PC; run `service prepare` under the enrolling account; confirm the service starts and reports `RUNNING`; reboot without logging in and confirm the server shows a fresh authenticated heartbeat; stop the service and confirm the heartbeat ceases; start it again and confirm reconnect; run foreground `labguard-agent run` while service is active and confirm it reports duplicate-instance refusal; inspect the state directory ACL and verify only the enrolling account, SYSTEM, and Administrators have access. Do not perform migration tests on a production identity without a backup and a controlled recovery plan.

The client tests are in `tests/`; install them with `python -m pip install -e ".[test]"` and run `python -m pytest -q` from this project.
