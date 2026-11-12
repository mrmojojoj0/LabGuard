# LabGuard Architecture Reports

These reports describe the architecture present in this repository as of 12 November 2026. They are based on the implementation and the feature notes under `docs/`; stated limitations are intentional parts of the system contract. They are not deployment or endpoint enforcement claims.

## Reports

1. [System architecture and data flow](01-system-architecture.md)
2. [Identity, enrollment, authentication, and audit](02-identity-enrollment-audit.md)
3. [Fleet, rooms, status, and live dashboard updates](03-fleet-rooms-status.md)
4. [Telemetry and inventory](04-telemetry-inventory.md)
5. [Network and peripheral activity](05-network-peripheral-monitoring.md)
6. [Software discovery and inventory](06-software-discovery-inventory.md)
7. [Software job lifecycle and execution](07-software-job-lifecycle.md)
8. [Remote operations: RDP and process control](08-remote-operations.md)
9. [Screenshots and evidence](09-screenshots-evidence.md)
10. [Exam scheduling, monitoring, and reporting](10-exam-management.md)
11. [Lab camera monitoring](11-camera-monitoring.md)

Each report separates the implemented pipeline from known gaps, and identifies the important persistence and protocol boundaries.
