# Exam Management Milestone (2026-11-11)

## Implemented foundation

- Dashboard navigation includes **Exams**. LAB_ADMIN and SUPER_ADMIN can schedule exams for a lab; all PCs assigned to that lab are included automatically and shown in their existing room-grid positions. A device cannot be assigned to overlapping scheduled or active exams.
- While an active exam has **Restrict common browsers** enabled, the server requests a process-name scan from connected target agents every 15 seconds. Matching Edge, Chrome, or Firefox processes create one deduplicated `RESTRICTED_BROWSER_RUNNING` alert per browser and device per exam; only browser names and counts are sent. If screenshot-on-violation is enabled, the existing automatic evidence flow is requested.
- Server validates timezone-aware start/end times, application executable restrictions, IPv4/IPv6 CIDR allow-lists, role/CSRF authorization, and room membership. A browser toggle expands to the stored `msedge.exe`, `chrome.exe`, and `firefox.exe` match list. Migration `0017_exam_management` stores exams and deduplicated violation records.
- A server monitor activates/completes scheduled exam records from UTC time and publishes dashboard SSE invalidations. It records an `AGENT_OFFLINE` alert during an active exam when a targeted device is not ONLINE.
- The monitor compares observed WFP allowed-connection events against an exam `ALLOW_LIST` and flags connected external USB storage when `block_usb_storage` is requested. Findings are persisted, audited and shown in reports.
- Every detected exam violation queues four captures at detection time and at +10, +20, and +30 seconds. The existing screenshot storage keeps them for 24 hours and allows manual deletion. A server-side dispatcher sends due captures; missed schedules or disconnected agents are marked failed. The endpoint needs an active console session and a compatible client.
- Report view includes target PC heartbeat state, offline/observed network/USB alerts, and timestamps. Browser Print supports “Save as PDF” without another PDF library.

## Important incomplete work / limitations

- **Endpoint restrictions are not enforced.** Exam policy is currently saved as desired configuration and is not delivered as an enforcement policy to the Windows agent. `network_mode=ALLOW_LIST` means monitor and alert on observed allowed WFP connections outside listed CIDRs; it does not block traffic. USB storage and common browsers are detected and flagged but not disabled/blocked. Restricted app executable names are stored but not monitored or blocked. Schedule transitions currently change server exam status; they do not activate/deactivate endpoint enforcement. Dashboard copy explicitly warns about this.
- **Anomaly coverage is partial.** Implemented signals are target agent non-ONLINE state, WFP allowed connection outside the configured CIDRs, USB storage connection, and periodic common-browser process scans during enabled active exams. There is no restricted-app process flow, tamper detection, policy receipt/hash attestation, persistent process event buffer, or proof of agent health beyond the existing authenticated heartbeat.
- **Evidence retention uses existing screenshot rules.** Auto-captures are stored by existing screenshot service/file storage and expire after 24 hours. Screenshot capture failure is visible in screenshot history, but a screenshot failure does not roll back the violation. Offline devices cannot be captured. Every violation creates four capture records, so exams with frequent alerts can produce substantial image storage.
- Exam report PC status now uses the room's current row/column assignments and grid dimensions. Moving PCs after an exam has been created can change the layout shown by a later report.
- A same-process server monitor is used, consistent with the existing MVP; multi-worker deployments would need a single scheduler/leader or database claim locking to avoid duplicate work.
- The server test suite and PostgreSQL migrations need verification in the project test environment. No real Windows restriction enforcement test has occurred.

## Verification in this workspace

- Dashboard `npm run typecheck`: passed.
- SQLite Alembic upgrade through `0018_exam_screenshot_bursts`: passed. Python source compilation passed for server and client.
- Dashboard `npm test`: could not start because Vite/Rolldown's native Tailwind binding failed to load (`spawn EPERM` / invalid UTF-8 from `@tailwindcss/oxide-win32-x64-msvc`).
- Server SQLite in-memory Alembic upgrade through `0017_exam_management`: passed.
- Direct SQLAlchemy/Pydantic smoke check: schema validation, room target validation, schedule activation, and offline alert passed.
- Full server pytest suite could not start: server virtualenv lacks pytest; client virtualenv's pytest lacks the server test HTTP client dependency (`httpx2` required by the installed Starlette). No dependencies were added.
- `git diff --check`: passed; Git reports only line-ending normalization warnings for existing modified files.

## Next steps / handoff

1. Add a versioned `server.exam.policy` delivery and `client.exam.state` acknowledgement on the existing authenticated WebSocket. Offline clients must receive only current nonexpired schedule state on reconnect.
2. Implement and report reversible Windows restriction adapters for exact restricted executable names, USB storage and a network allow-list. Persist pre-exam machine settings and restore them on schedule end, cancel, policy replacement, service restart, and expired offline policy. Preserve the server route and heartbeat, and always exempt/validate LabGuard server connectivity.
3. Add bounded process monitoring for configured restricted apps, persistent local event buffering/acknowledged upload, policy version/hash receipt, service/config tamper signals, and tests for restart/offline recovery.
4. Correlate app/browser violations with reports and automatic screenshots; test auto-capture throttling and expired/missing-console failure behavior.
5. Run the full server and dashboard test suites, PostgreSQL migration/transaction checks, and supervised Windows VM tests for restriction activate/restore, service crash/restart, and policy schedule transitions before representing enforcement as complete.

Do not present the current policy form as a functioning endpoint blocker until those steps pass.
