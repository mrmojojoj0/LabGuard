# Remote Operations: RDP Preparation and Process Control

## Overview

LabGuard exposes two narrowly scoped remote operations: a time-limited Windows Remote Desktop preparation lease and PID-bound process inspection/termination. Both require an online, authenticated endpoint for immediate delivery. They are typed requests with durable server records and audit history, not an interactive remote-control channel.

## RDP preparation pipeline

1. A LAB_ADMIN submits a CSRF-protected request for an enabled, approved, online device with an acceptable hostname.
2. The server persists and audits an `RdpAccessRequest`, with a short acceptance deadline and a bounded access lease (60 minutes after acceptance).
3. The server offers `server.rdp.access.request` to the active authenticated socket. If delivery fails, the request becomes failed rather than silently queued.
4. The agent validates request ID/expiry and evaluates Windows edition, elevation/service context and firewall prerequisites. Unsupported Home editions, policy denial, non-elevated execution and firewall failure fail closed.
5. On success, the agent applies a reversible configuration lease: it records original relevant registry/policy values, enables the listener, applies the narrowly required local-account setting, and adds request-specific TCP/3389 firewall rules. The result is returned with request identity and sequence context.
6. Server binds the result to the device/request, persists terminal status and makes it queryable. Lease expiry triggers restoration of saved values and firewall state.

The endpoint configuration is not a permanently open RDP toggle: it is bounded by the lease and restoration path. Access still depends on Windows credentials, network reachability and firewall policy. The server does not relay an RDP desktop session.

## Process operation pipeline

1. LAB_ADMIN submits a typed LIST, TERMINATE or KILL request; termination includes a selected PID and process creation timestamp.
2. Server rejects offline devices, creates an expiring durable request (90-second validity), audits it, and sends a typed WebSocket message.
3. Agent lists process metadata or resolves the target PID. Before termination it compares the process creation time against the requested timestamp, preventing PID reuse from selecting a different process.
4. The endpoint enforces its local restrictions and reports a bounded typed result. Server binds the result to the authenticated device and request ID and persists it.
5. Dashboard polls/refetches the persisted request result and shows the actual state.

## Safety and failure model

Requests are short-lived, specific to a device, authenticated, audited and schema-validated. No free-form command, executable path, process name wildcard or shell is accepted. Offline requests fail rather than accumulating into a surprise future action. Elevated permissions and Windows edition are checked locally. Errors are explicit, and server success is based on an endpoint result rather than message delivery alone.

## Source map and constraints

Server request state is in `rdp_access.py` and `process_management.py`; route delivery is in `api.py`; socket event helpers are in `websocket.py`. Client adapters are in `rdp_access.py` and `process_control.py`. These operations are separate from screenshot capture and do not provide general desktop control. Live Windows lease restoration and real process tests remain deployment checks.
