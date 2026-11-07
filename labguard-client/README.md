# LabGuard Client

Windows endpoint agent for authenticated device enrollment, heartbeat, telemetry, software inventory, individual WinGet/Chocolatey jobs, and LAB_ADMIN-requested temporary RDP access. It does not provide arbitrary remote execution, process control, packet capture, or USB monitoring.

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

For the repository launcher, set `LABGUARD_SERVER_URL` to the server base URL, then run `Start-LabGuard-Client.bat enroll`. After approval, run the launcher without arguments. HTTP requires explicit development opt-in by setting `LABGUARD_ALLOW_INSECURE_DEV=1`; keep certificate verification enabled for HTTPS/WSS. See `../docs/LabGuard_LAN_Deployment.md` for LAN guidance.

After an administrator approves the pending UUID and assigns a name, start the agent:

~~~powershell
labguard-agent run --server https://labguard.example.edu
~~~

The agent verifies TLS using the operating system trust store for HTTPS connections, proves possession of its Ed25519 private key, obtains a short-lived one-use WebSocket ticket, sends hello, and sends application heartbeats at the server-provided interval. It collects CPU, memory, storage, Windows/OS, uptime, and network interface metadata immediately after authentication and every 30 seconds by default. Configure the foreground interval with `--telemetry-interval-seconds` or `LABGUARD_TELEMETRY_INTERVAL_SECONDS` (10–3600 seconds); for a service, supply the value to `service prepare`. Collection runs off the heartbeat loop, and collection or telemetry rejection errors do not stop heartbeat operation. The collector does not inspect user files or browsing information. It reconnects with capped exponential backoff and jitter. Both HTTP and HTTPS server URLs are accepted; HTTPS remains certificate-verified.

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

`prepare` requires the existing `%PROGRAMDATA%\LabGuard\identity.json`; it migrates DPAPI protection from current-user scope to machine scope while retaining the UUID, key, and sequence. It writes the server URL, state path, and transport policy to `service.json`. The protected ACL grants file/directory full access only to the enrolling account, LocalSystem, and Administrators, with file and directory inheritance retained. HTTPS certificate verification remains enabled. The service runs as LocalSystem, starts automatically with Windows, logs to `%PROGRAMDATA%\LabGuard\labguard-agent.log`, retries disconnected sessions, and stops by cancelling active async operations and closing the WebSocket. A cross-process lock beside the identity prevents a foreground process and service from using the same identity together.

`service prepare` accepts HTTP or HTTPS URLs. Existing `--insecure-dev` flags remain accepted for compatibility but do not affect URL validation. HTTPS uses the operating system certificate trust store. Example local development setup:

~~~powershell
py -3.12 -m labguard_client.cli service prepare --server http://127.0.0.1:8000
py -3.12 -m labguard_client.cli service install
~~~

Manage it with `py -3.12 -m labguard_client.cli service start|stop|restart|status|uninstall`. Uninstall retains the identity and configuration. Installation is idempotent. Service management requires an elevated prompt. Do not run the foreground agent while the service is active.

Windows Service runtime behavior, actual DPAPI machine-scope migration, ACL enforcement, and automatic startup require verification on Windows. On startup the pywin32 framework reports `SERVICE_RUNNING` before calling LabGuard's `SvcDoRun`; heavyweight agent imports and network initialization happen after that report. For venv installs, service installation stages the host in `.venv\Scripts` with the matching runtime DLLs so the venv's `pyvenv.cfg` and `Lib\site-packages` resolve correctly under LocalSystem. Existing stopped venv services are updated to the staged host without changing their account or startup mode. The service initializes `%PROGRAMDATA%\LabGuard\labguard-agent.log` before reading configuration or decrypting identity and records Python executable/DLL/import paths plus startup exceptions.

On Krypton, rebuild and update the service from elevated PowerShell. This uses the existing configuration and identity; HTTP installations still require the persisted development opt-in and the explicit install flag:

~~~powershell
$ClientRoot = 'C:\Users\sakin\OneDrive\Desktop\LabGuard\labguard-client'
$AgentPython = Join-Path $ClientRoot '.venv\Scripts\python.exe'
sc.exe stop LabGuardAgent
Start-Sleep -Seconds 3
Push-Location $ClientRoot
& $AgentPython -m pip wheel --no-deps --no-build-isolation --wheel-dir .\dist .
$Wheel = Get-ChildItem -LiteralPath (Join-Path $ClientRoot 'dist') -Filter 'labguard_client-*.whl' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
& $AgentPython -m pip install --no-deps --force-reinstall $Wheel.FullName
Pop-Location
& $AgentPython -m labguard_client.cli service install --insecure-dev
sc.exe qc LabGuardAgent
sc.exe queryex LabGuardAgent
reg.exe query HKLM\SYSTEM\CurrentControlSet\Services\LabGuardAgent /v ImagePath
reg.exe query HKLM\SYSTEM\CurrentControlSet\Services\LabGuardAgent\PythonClass
Get-ChildItem (Join-Path $ClientRoot '.venv\Scripts') -Filter '*.dll'
sc.exe start LabGuardAgent
Start-Sleep -Seconds 5
sc.exe queryex LabGuardAgent
Get-Content C:\ProgramData\LabGuard\labguard-agent.log -Tail 100
~~~

The service now registers the active base Python runtime directory with `os.add_dll_directory()` before importing `DeviceIdentity` and cryptography. The directory handle is retained for the process lifetime. This supplies `python3.dll`, which `_rust.pyd` imports, when LocalSystem does not have the interactive user's Python directory on PATH. The service also creates and installs an `asyncio.SelectorEventLoop` in the pywin32 service thread; the foreground client keeps its existing event-loop behavior. This avoids the default Windows Proactor loop's main-thread-only signal wakeup setup. Service stop/shutdown signal the loop thread-safely, after which pending tasks are cancelled and the loop is closed. Startup exceptions continue to include full tracebacks in the protected log. The direct `pythonservice.exe -debug LabGuardAgent` invocation is not an SCM startup test and must not be used as proof of the root cause. Verify that `ImagePath` now ends in `.venv\Scripts\pythonservice.exe`, confirm `sc.exe queryex` reports RUNNING and a nonzero PID, and inspect the log for `Registered Python native runtime DLL directory`, runtime paths, and an authenticated connection. Review server job state before starting the service because it resumes the existing authenticated agent and may receive already-authorized pending jobs. Then verify stop/restart behavior and inspect the protected state ACL. Do not perform migration tests on a production identity without a backup and controlled recovery plan.

The client tests are in `tests/`; install them with `python -m pip install -e ".[test]"` and run `python -m pytest -q` from this project.

## Software inventory

After WSS authentication, the client reads installed application metadata from the Windows uninstall registry in both 64-bit and 32-bit views, and from HKCU plus ordinary user registry hives that are currently loaded and accessible. It reports bounded app name, version, publisher, architecture, install date/location, package identifier, source, and machine/user scope. It does not read uninstall command lines, run installers, or inspect user files. Registry access failures are recorded as bounded error codes and make the scan partial.

If available, the agent also queries WinGet and Chocolatey with fixed argument lists and no shell. Those results are identified by source; package manager absence or failure does not discard registry results. WinGet inventory and job execution share one resolver: it checks the current execution identity's WindowsApps alias and the machine App Installer package directories under `ProgramW6432`, `ProgramFiles`, and `ProgramFiles(x86)`, before accepting PATH results that resolve to one of those known locations. Machine App Installer discovery does not depend on an interactive user's PATH or profile, so it can locate the executable under LocalSystem in Session 0. The agent logs a reason code for missing executable, access denial, timeout, App Installer registration, command failure, or unusable output, along with the account/session and safe environment-presence facts. Per-user applications in unloaded hives are omitted. Foreground collection can read the current user's accessible hive; a service only sees loaded hives accessible to its service token. Do not switch service accounts as a workaround for software management. A live LocalSystem inventory and installation check remains required on Krypton.

Inventory is sent over the existing ticket-authenticated WSS session as typed `client.software_inventory` batches, capped at 48 KiB and 100 entries per batch. A matching `server.ack` acknowledges each batch. The client sends a full initial scan, then reports an unchanged digest without resending entries when nothing changed. It scans every six hours by default. Configure `--software-inventory-interval-seconds` or `LABGUARD_SOFTWARE_INVENTORY_INTERVAL_SECONDS`; allowed values are 300 seconds to 7 days. The same CLI option/environment variable is used by service preparation, and older service configuration files default to six hours. A server-issued `server.software_inventory.refresh` event triggers an immediate full scan. Inventory collection runs in a worker thread and failures do not interrupt heartbeat handling.

Manual Windows inventory verification: install and approve a disposable test device, start the service, and wait for its initial collection to appear in the dashboard. Compare a few entries against Windows Installed Apps or the uninstall registry. While the device is online, request a refresh from its Software tab and confirm the last-success time advances. To inspect per-user behavior, test once with a user hive loaded and once with it unloaded; loaded, accessible hives should be collected, unloaded profiles are omitted, and access-denied keys should appear as partial collection health. These checks require an actual Windows host and are not covered by the platform-independent unit suite.

Inventory reconciliation merges only unambiguous WinGet/Registry pairs using exact package ID or normalized name plus equal publisher/version evidence. Known edition, version, publisher, architecture, scope, or package-ID conflicts keep rows separate. The preferred source is WinGet when it supplied the reliable package ID; `discovery_sources` preserves provenance. Unmatched and ambiguous Registry applications remain visible. This is covered by deterministic reconciliation tests; a live endpoint scan should confirm matches against its installed-app list.

## Individual software jobs (v0.6)

The agent accepts exact WinGet IDs selected through the server's fixed community-source search, plus existing approved Chocolatey jobs, over its existing authenticated WSS session. The server validates direct WinGet identity and selected version before persisting a job. Chocolatey requires the server's configured `CHOCOLATEY_SOURCE_URL`. Package manager invocations use fixed argument lists, no shell, bounded runtime/output, and a durable job journal. A fresh complete inventory scan verifies the requested install/uninstall before the agent reports success.

Machine-scope jobs require an elevated administrator or LocalSystem. USER-scope WinGet jobs are refused in Session 0 under LocalSystem or any custom service account; they are supported only in a foreground interactive process. LabGuard does not impersonate a user or launch a helper. Chocolatey is machine-only and its existing approved catalog job path is unchanged. Uninstall is available only for a present inventory row with one exact supported package ID and scope; it no longer depends on a catalog approval. Fixed WinGet or existing Chocolatey adapters perform uninstall, and a complete fresh scan must verify the package is absent before success. Interactive-only uninstallers and incomplete scans fail safely. No registry uninstall command strings are run. Tests use mocked subprocesses; actual package operations require controlled Windows-host verification. See `../docs/LabGuard_Development_State.md` for remaining checks.

## Temporary RDP access

An authenticated LAB_ADMIN request arrives over the existing device-ticket WSS connection. The agent requires an elevated or LocalSystem token, rejects Windows Home and policy-disabled RDP, preserves the current `fDenyTSConnections` value, and creates fixed TCP/3389 firewall rules for the local subnet on Domain/Private profiles only. Network Level Authentication is unchanged. A machine registry marker stores the prior setting and lease expiry so cleanup continues after service restart. After 60 minutes the agent restores the previous RDP setting and removes only its own firewall rules. Repeated requests extend the active lease. Windows account credentials are never collected. Actual listener, firewall and timeout behavior requires controlled Windows endpoint validation.
