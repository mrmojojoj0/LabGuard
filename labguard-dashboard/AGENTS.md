# LabGuard Dashboard Agent Instructions

This is an independent React/Vite administrative dashboard. Do not modify `labguard-server` or `labguard-client` from this project. Treat the existing server API as the contract; do not simulate missing backend capabilities or invent API routes/events.

- Keep all HTTP calls in `src/features/*/api.ts` or `src/lib/api.ts`.
- Admin sessions are HttpOnly cookies. Always use `credentials: "include"`; send the in-memory/session-tab CSRF token in `X-CSRF-Token` for mutations.
- Never store administrator passwords or session cookies/secrets in browser storage. Do not expose device private keys or password hashes.
- Honor server roles for controls, but rely on server RBAC as authority.
- The agent WebSocket accepts only device ticket credentials and agent events. Never connect the dashboard to it.
- Mark unsupported data/actions as unavailable or coming soon. No fake responses.
- Do not implement remote control, arbitrary execution, deployment, process termination, or USB blocking.
