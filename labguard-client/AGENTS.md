# LabGuard Client Agent Instructions

This is the independent Windows Python endpoint service. Follow ../docs/LabGuard_Architecture.md as protocol/security contract. Do not import server internals or make a shared deployable.

- Target the institution-approved Windows baseline; isolate Windows APIs behind adapters. Run as a least-privilege Windows Service.
- Session 0 cannot control the interactive desktop. Any user-session helper is a separate later process requiring explicit scope and user-visible behavior.
- Generate/persist a random device UUID and per-device asymmetric key. Protect private key material with DPAPI or certificate store and restrictive service ACLs.
- Verify TLS certificates for HTTPS/WSS; never fall back to plaintext or disable verification. MAC/IP/hostname are mutable inventory, never identity or authentication.
- Validate versioned protocol and allowlisted job schemas. Reject unknown, expired, malformed, unauthorized, or duplicate jobs safely.
- No arbitrary shell, free-form command strings, unsafe command-line concatenation, stealth, credential collection, security bypass, or hidden desktop control.
- Persist idempotency/result state before side effects. Bound retries, output, queues, log size, and job duration. Reconnect with exponential backoff and jitter.
- Collect only configured and disclosed inventory. Distinguish collection errors from empty results. Never use Win32_Product.
- MVP handlers are read-only diagnostics and inventory/statistics. Installers, process termination, restart/shutdown, packet capture, updater, and GUI automation need later explicit design and approval.
- Keep secrets out of logs/config files. Report collection and server receipt times distinctly; client time does not establish liveness.
- Do not begin Phase 1 until the project owner declares architecture review complete and authorizes implementation.
