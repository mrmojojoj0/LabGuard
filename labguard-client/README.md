# LabGuard Client

Minimal Windows endpoint agent for authenticated device enrollment and heartbeat communication. It has no remote execution, software deployment, process control, packet capture, or USB monitoring functionality.

## Install

Use the institution-approved Python 3.12+ runtime. On Windows, install the Windows extra for DPAPI-backed private key storage:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[windows]"
~~~

The identity file is stored under `%PROGRAMDATA%\LabGuard\identity.json` by default. Its private key is protected by Windows DPAPI for the current Windows service/user identity. Keep the state directory ACL restricted to the account that runs the agent and Administrators. Do not copy the encrypted identity to another PC or run the service under a different account without a controlled re-enrollment.

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

The agent verifies TLS using the operating system trust store, proves possession of its Ed25519 private key, obtains a short-lived one-use WebSocket ticket, sends hello, and sends application heartbeats at the server-provided interval. It reconnects with capped exponential backoff and jitter. Plain HTTP is rejected unless `--insecure-dev` is explicitly set for local development.

This milestone provides a foreground process, not Windows Service installation/packaging. Service setup, ACL provisioning, signed installer, and update lifecycle remain later work. The client tests are in `tests/`; install them with `python -m pip install -e ".[test]"` and run `python -m pytest -q` from this project.
