# LabGuard Server Agent Instructions

This is the independent FastAPI server project. Follow ../docs/LabGuard_Architecture.md and ../docs/LabGuard_Development_State.md as the current contract. The implementation baseline is through v0.6. Do not add client runtime code or create a third deployable.

- Use FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL. Keep routes thin; business rules and transactions belong in services.
- Version REST and WebSocket schemas under v1. Validate all input and treat client reports as untrusted. Use UUID identity and UTC time.
- Device UUID is identity. MAC, IP, and hostname are inventory only. Keep agent state separate from network reachability; derive liveness from server-received authenticated heartbeat.
- Enforce RBAC on every admin action. Use secure password hashing, revocable server-side sessions, CSRF protection, and transactional audit for privileged changes.
- Enrollment stays pending until explicit admin approval. Never trust MAC/IP/hostname as identity.
- Use typed, versioned, allowlisted jobs. v0.6 has approved catalog entries and persistent individual software jobs. Never implement unrestricted shell, free-form command text, arbitrary executable paths, or administrator-supplied download URLs. Exam schedules and violation records are a separately authorized milestone; policy records do not prove endpoint enforcement.
- Reuse `SoftwareJob`, the catalog, and the authenticated WSS delivery/event path for a future bulk deployment milestone; do not create a second job system. Persist authorized targets before dispatch, audit requests, and make redelivery/replay safe. Bulk target atomicity, concurrency, retries and cancellation need an explicit v0.7 design before coding.
- Bound payloads, queues, logs, and outputs; redact secrets. Keep the UI same-origin and avoid broad CORS.
- Software inventory and individual approved WinGet/Chocolatey jobs are implemented. Bulk deployment, auto-update, process termination, packet capture, remote desktop, arbitrary commands and user-session helper remain out of scope until separately authorized.
- Keep secrets out of configuration examples. Add migrations for model changes. Preserve transaction boundaries around enrollment, layout, job fan-out, and audit. Separate live and ready health checks.
- Keep REST authorization/CSRF, authenticated device identity, audit and Alembic migration coverage consistent with current code. SQLite migration tests do not substitute for PostgreSQL verification.
