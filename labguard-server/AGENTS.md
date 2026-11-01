# LabGuard Server Agent Instructions

This is the independent FastAPI server project. Follow ../docs/LabGuard_Architecture.md as its contract. Do not add client runtime code or create a third deployable.

- Use FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL. Keep routes thin; business rules and transactions belong in services.
- Version REST and WebSocket schemas under v1. Validate all input and treat client reports as untrusted. Use UUID identity and UTC time.
- Device UUID is identity. MAC, IP, and hostname are inventory only. Keep agent state separate from network reachability; derive liveness from server-received authenticated heartbeat.
- Enforce RBAC on every admin action. Use secure password hashing, revocable server-side sessions, CSRF protection, and transactional audit for privileged changes.
- Enrollment stays pending until explicit admin approval. Never trust MAC/IP/hostname as identity.
- Use typed, versioned, allowlisted jobs. Never implement unrestricted shell, free-form command text, or arbitrary executable paths.
- Persist parent job and per-device target state before dispatch. WebSocket memory is a delivery optimization; duplicate offers must be safe.
- Bound payloads, queues, logs, and outputs; redact secrets. Keep the UI same-origin and avoid broad CORS.
- Defer discovery, packet capture, process termination, software deployment, direct installers, GUI helper, and updater unless a scoped phase calls for them.
- Keep secrets out of configuration examples. Add migrations for model changes. Preserve transaction boundaries around enrollment, layout, job fan-out, and audit. Separate live and ready health checks.
- Do not begin Phase 1 until the project owner declares architecture review complete and authorizes implementation.
