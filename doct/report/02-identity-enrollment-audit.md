# Identity, Enrollment, Authentication, and Audit

## Trust model

LabGuard has two distinct principals: human administrators and endpoint devices. Human sessions use server-managed revocable credentials and role-based access. A device is identified by a persistent UUID and an Ed25519 key pair; the private key remains on the endpoint under Windows DPAPI or an equivalent protected store. Network addresses and machine names are descriptive metadata and never authenticate a device.

## Device enrollment pipeline

1. An authorized administrator generates a short-lived one-time enrollment code. The raw code is returned to the administrator; the server stores a digest and expiry/consumption state.
2. The agent creates or loads a UUID and key pair, then sends the code, public key, hostname and agent version to `/api/v1/enrollment/request`.
3. The server rate-limits attempts, validates and consumes the enrollment code, and creates a pending device plus credential fingerprint. Submission does not grant operational trust.
4. A LAB_ADMIN reviews pending enrollments and explicitly approves with an assigned display name or rejects. Approval is audited and changes the enrollment state.
5. Subsequent device authentication uses a server challenge signed by the bound private key. The server checks the registered, non-revoked public key and issues a short-lived, single-use WebSocket ticket.
6. The ticket is stored hashed, bound to a device, expires quickly, and is consumed on connection. The authenticated socket becomes the authority for subsequent device events.

The server derives the device ID from the authenticated ticket/session. A payload-supplied device UUID alone never authorizes ingestion. Credential revocation is a SUPER_ADMIN action; it marks the device quarantined, writes audit state, and closes an active socket when present.

## Administrator authentication and authorization

Login validates credentials using the server's password hashing configuration, establishes a durable session record, and returns the administrator's role and CSRF token. The session token is an HttpOnly cookie with secure and SameSite settings. Logout revokes the server session and deletes the cookie. Session revocation means a copied cookie can be invalidated server-side.

Mutating browser routes require CSRF validation in addition to authentication. Role dependencies gate every admin action (VIEWER, OPERATOR, LAB_ADMIN, SUPER_ADMIN); the dashboard role controls improve usability but do not replace server authorization. Login failures and enrollment/device-auth attempts have in-process rate limits in the current single-instance design.

## Audit pipeline

Privileged state changes are recorded with the associated database transaction wherever required: actor, action, target type/identifier, timestamp, and bounded relevant details. Device-originated activity is attributed through the authenticated connection. Device deletion writes a retained audit snapshot/text target so that the audit history can outlive cascaded device-owned rows. Auditing is not merely a dashboard log; it is durable server-side history.

## Security properties and limits

- TLS verification stays enabled for HTTPS/WSS. Insecure HTTP/WS requires explicit development opt-in.
- Enrollment remains pending until human approval; possession of a code only requests enrollment.
- Key revocation prevents future authentication and closes the current connection where possible.
- Device and administrator protocols are separate; a device ticket cannot authenticate a browser.
- Rate limits and active connection registries are currently process-local. Multi-worker operation requires shared coordination.
- Existing HTTP and HTTPS support includes a compatibility development flag; deployment must configure trusted certificates and secure session cookies.

## Source map

Server auth and enrollment routes are in `api.py`; session, challenge, ticket, enrollment and audit transaction logic is in `services.py` and `security.py`. Device ticket validation and event attribution are in `websocket.py`. Client identity protection and signing are in `identity.py` and `agent.py`. Schema changes are in migrations and `models.py`.
