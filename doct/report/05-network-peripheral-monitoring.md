# Network and Peripheral Activity Monitoring

## Two network data planes

LabGuard has two complementary network records. Periodic socket snapshots provide a point-in-time view of active TCP/UDP sockets, while Windows Filtering Platform (WFP) Security audit events provide historical allow/block decision metadata. They have different collection sources and failure modes and should not be conflated.

## WFP event collection and acknowledgement algorithm

1. During service setup, the client enables Windows Filtering Platform Connection success/failure auditing. The reader queries Security event records 5156 (permitted connection), 5157 (blocked connection), and 5152 (blocked packet); listener events are excluded because they do not identify the remote peer.
2. A per-machine cursor tracks the last acknowledged event record and log generation. On first run it starts at the current log end, intentionally avoiding pre-install backfill.
3. The collector renders records to bounded normalized fields, places them in a bounded queue (maximum 5,000 retained events), and sends small batches (up to 25) over the existing authenticated WebSocket.
4. Server ingestion derives device ID from the socket, validates the event, deduplicates by device + log generation + event record ID, stores it separately from socket snapshots, and applies configured retention (30 days).
5. The client advances/persists its cursor only after server acknowledgement. This supports retry after disconnect without silently skipping unacknowledged events.
6. Log clear/rollover and query/access failures are exposed as per-device collection state. Health refreshes on startup, on changes and periodically (at least once per minute).

The event feed records decision metadata, not packet contents. It does not guarantee visibility of every UDP datagram, ICMP packet, or blocked packet: Windows policy and event emission determine coverage. There is no packet capture, URL extraction, decrypted HTTPS inspection, ETW trace or network driver.

## Socket snapshot pipeline

The agent uses psutil to collect current TCP/UDP socket metadata on a periodic interval (30 seconds by default). The server stores snapshots for latest/history views. Snapshots may miss short-lived flows and do not replace the WFP historical feed.

## Peripheral activity

USB/peripheral observation is gathered from Windows device state and uploaded as a bounded activity snapshot/history. Exam monitoring can compare connected external USB storage with requested policy and record a finding. This is observational: the current exam foundation does not disable USB storage. A reported peripheral observation is not proof of a complete device audit across every Windows driver/device class.

## Enrichment and query path

Remote public IP enrichment is performed server-side and only for globally routable addresses. Private, loopback and otherwise non-public addresses are not sent to the external IPinfo Lite lookup. Network history endpoints filter by device/event kind and paginate. The admin SSE event tells the dashboard to refetch; stored rows remain canonical.

## Operational prerequisites and limitations

The Windows audit policy can be overridden by domain policy and should be verified after installation. Security log size and overwrite policy determine how much history can be retained; overwritten records cannot be recovered. A detectable generation change is reported as a gap. Test live Windows events and rollover under realistic load. PostgreSQL migration execution and end-to-end dashboard delivery also need deployment verification.

## Source map

Client modules: `network_events.py`, `telemetry.py`, `peripherals.py`, and service setup. Server ingestion/query modules: `wfp_activity.py`, `network_activity.py`, `peripheral_activity.py`, and `telemetry.py`; event schemas and storage are in `schemas.py`, `models.py`, and migrations.
