# LabGuard Dashboard Agent Instructions

This is an independent React/Vite administrative dashboard. Treat the existing server API as the contract; do not simulate missing backend capabilities or invent API routes/events. Changes to server/client are outside this project's scope unless the user explicitly authorizes a cross-project task.

- Keep all HTTP calls in `src/features/*/api.ts` or `src/lib/api.ts`.
- Admin sessions are HttpOnly cookies. Always use `credentials: "include"`; send the in-memory/session-tab CSRF token in `X-CSRF-Token` for mutations.
- Never store administrator passwords or session cookies/secrets in browser storage. Do not expose device private keys or password hashes.
- Honor server roles for controls, but rely on server RBAC as authority.
- The agent WebSocket accepts only device ticket credentials and agent events. Never connect the dashboard to it.
- Mark unsupported data/actions as unavailable or coming soon. No fake responses.
- The separately authorized Exam Management foundation uses existing room assignments, server schedules, heartbeat state, WFP/peripheral history and screenshot APIs. Clearly label desired policies as unenforced until the client confirms an applied policy version; never present a saved exam policy as proof that a restriction is active.
- v0.6 individual software management is implemented at `/deployment` and in device Software tabs. Keep catalog approval Super Admin-only, job creation LAB_ADMIN+, and rely on server-side RBAC/CSRF. Show persisted job state only; do not fabricate progress/results.
- A future bulk deployment page must reuse existing catalog and job APIs/infrastructure after the v0.7 contract exists. Do not add bulk deployment, remote control, arbitrary execution, process termination, or USB blocking during a v0.6 maintenance task.
