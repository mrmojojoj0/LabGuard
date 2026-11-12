# Exam Scheduling, Monitoring, and Reporting

## Current capability statement

Exam Management is a server-side scheduling, monitoring and evidence foundation. Saved restrictions are desired policy records only. The current client does not receive and enforce exam policy, so the system must not claim it blocks browsers, applications, USB storage or network traffic.

## Scheduling pipeline

1. A LAB_ADMIN or SUPER_ADMIN submits an exam with timezone-aware start/end times, room, configured executable restrictions, network mode/CIDR allow-list, browser restriction toggle, USB storage flag and evidence settings.
2. Server validates times, role/CSRF, supported executable names, CIDR syntax and room membership. The room's assigned device IDs become the persisted target set.
3. Overlap checks prevent a device from being targeted by overlapping scheduled/active exams. The exam record and audit event are persisted.
4. A same-process monitor evaluates UTC time, changes SCHEDULED to ACTIVE and later to COMPLETED, publishing dashboard SSE invalidations. Cancellation is a separate authorized transition.

## Monitoring algorithm

During an active exam, the monitor evaluates current target status and available observations:

- A target that is not ONLINE can create an `AGENT_OFFLINE` violation.
- If common browser restriction is enabled, the server asks connected agents for a process-name scan every 15 seconds. The agent returns browser names/counts, not full process lists. Edge, Chrome and Firefox matches create one deduplicated `RESTRICTED_BROWSER_RUNNING` finding per browser/device/exam.
- Network mode `ALLOW_LIST` compares observed allowed WFP connection events with the configured CIDRs. An outside connection is flagged; traffic is not blocked.
- A connected external USB storage device can create a finding when the exam requests USB blocking; it is observed, not blocked.
- Restricted executable names are stored, but the implemented monitoring flow does not scan/report those names.

Violations are persisted and deduplicated according to exam/device/kind or browser identity. Findings can trigger a four-image screenshot burst using the existing screenshot service. Evidence capture status remains independent from the violation record.

## Reports and dashboard behavior

The Viewer+ exam report assembles the exam record, current room grid, targeted device heartbeat state and bounded recent violation history. Device positions are read from the current room layout, so later room edits can change historical display placement. Browser Print supports saving the report as PDF. The dashboard explicitly warns that desired policies are unenforced.

## Reliability and architecture concerns

The monitor and due-capture dispatcher run in the server process. This is suitable for the current single-instance MVP but can duplicate work or miss work under multiple workers/restarts without leader election/claim locking and durable scheduling semantics. Offline targets cannot provide fresh observations or screenshots. WFP signals only cover OS-emitted events. Screenshot volume can rise quickly with frequent alerts.

## Missing enforcement milestone

Enforcement requires a new typed/versioned policy delivery and applied-state acknowledgement, expiry and offline/restart recovery, reversible adapters, original-state persistence, restoration on end/cancel/replacement, and health reporting. Required scopes include restricted app process monitoring, browser handling, USB storage and network allow-list adapters. It also needs persistent local event buffering/acknowledged upload, policy version/hash receipt, tamper signals and supervised Windows validation. Until these exist and pass, an active server schedule is not an active endpoint restriction.

## Source map

Server validation, schedule state and monitor are in `exam_management.py` and `main.py`; API/report assembly is in `api.py`; models and migration `0017_exam_management` persist schedules/violations. The dashboard feature lives under `src/features/exams`; browser scan and observations use the existing agent WebSocket pipeline.
