# LabGuard v0.5 Software Inventory

## Collection

The Windows agent reads uninstall metadata from HKLM machine registry views, HKCU, and ordinary user hives loaded under HKEY_USERS. It best-effort queries winget and Chocolatey with fixed argument lists and no shell. It does not read uninstall command strings, run installers, or inspect personal files. A LocalSystem service cannot see a user hive that Windows has not loaded. Unavailable registry keys and optional package-manager errors are reported as bounded diagnostic codes.

## Protocol

Inventory extends the existing ticket-authenticated WSS protocol; envelope schema version remains 1. client.software_inventory carries inventory version 1, collection UUID and start time, batch index/count, complete/partial status, a SHA-256 digest, bounded errors, and up to 100 normalized entries. The payload omits device identity; the server associates it with the authenticated ticket. Frames remain below the existing 64 KiB maximum. Each batch receives a correlated server.ack.

Complete unchanged scans send only the digest and refresh the last-success timestamp. A server-issued server.software_inventory.refresh carries a request UUID. The WSS handler accepts that UUID only when it matches the pending administrator request for that authenticated device. The client responds with a full scan. Collection runs independently from heartbeat processing.

## Persistence and API

Alembic migration 0004_software_inventory adds collection records, unique per-collection batch receipts, and per-device software entry rows. Stable per-device entry keys update observed rows. A complete scan marks previously present entries not seen in that scan as absent; a partial scan never reconciles absence. This is evidence of “not observed,” not proof of an uninstall. Entry history remains until device removal. Collection/batch history is retained for 90 days by default.

Viewer+ roles can read:

- GET /api/v1/devices/{device_id}/software
- GET /api/v1/software
- GET /api/v1/software/summary
- GET /api/v1/software/{software_key}/installations

LAB_ADMIN+ with CSRF can request an online scan using POST /api/v1/devices/{device_id}/software/refresh. Each request is audited and per-device cooldown is 300 seconds by default. Offline devices return HTTP 409. Inventory becomes stale after seven days by default. The admin SSE stream emits a metrics-free software.inventory invalidation when a collection completes.

Settings: SOFTWARE_INVENTORY_REFRESH_COOLDOWN_SECONDS, SOFTWARE_INVENTORY_STALE_AFTER_SECONDS, and SOFTWARE_INVENTORY_RETENTION_DAYS.

This milestone does not add installation, uninstallation, updates, deployment, or arbitrary execution.
