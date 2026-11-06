# LabGuard Client Agent Instructions

This is the independent Windows Python endpoint agent. Follow ../docs/LabGuard_Architecture.md and ../docs/LabGuard_Development_State.md as protocol/security contract. Do not import server internals or make a shared deployable.

- Target the institution-approved Windows baseline; isolate Windows APIs behind adapters. The implemented pywin32 service currently runs as LocalSystem to access machine-scope DPAPI identity state; do not silently change its service account. Keep operations constrained and report this account choice when changing service security.
- Session 0 cannot control the interactive desktop. Any user-session helper is a separate later process requiring explicit scope and user-visible behavior.
- Generate/persist a random device UUID and per-device asymmetric key. Protect private key material with DPAPI or certificate store and restrictive service ACLs.
- Verify TLS certificates for HTTPS/WSS; never fall back to plaintext or disable verification. MAC/IP/hostname are mutable inventory, never identity or authentication.
- Validate versioned protocol and allowlisted job schemas. Reject unknown, expired, malformed, unauthorized, or duplicate jobs safely. v0.6 package jobs must match the server-approved catalog authorization and exact package identity.
- No arbitrary shell, free-form command strings, unsafe command-line concatenation, arbitrary URLs/paths, stealth, credential collection, security bypass, or hidden desktop control. Package-manager subprocesses use fixed argument lists, `shell=False`, bounded runtime/output, and safe discovery.
- Persist idempotency/result state before side effects. Bound retries, output, queues, log size, and job duration. Reconnect with exponential backoff and jitter.
- Collect only configured and disclosed inventory. Distinguish collection errors from empty results. Never use Win32_Product.
- v0.5 inventory is read-only; v0.6 adds only individual approved WinGet/Chocolatey install/uninstall jobs. Preserve the durable job journal and do not repeat uncertain RUNNING operations after reconnect. Bulk deployment, updates, process termination, restart/shutdown, packet capture and GUI automation require a separately authorized milestone.
- Machine-scope operations require elevation. Reject USER-scope jobs from all Session 0 service processes, not only LocalSystem. Do not impersonate users, silently switch accounts, or create an interactive helper.
- Keep secrets out of logs/config files. Report collection and server receipt times distinctly; client time does not establish liveness.
- Test package-manager operations only with mocked executables. Record actual Windows service, DPAPI, ACL, WinGet and Chocolatey checks as manual verification until performed.
