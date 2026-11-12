# Telemetry and Inventory

## Overview

LabGuard collects bounded system telemetry and software inventory through separate agent loops. Telemetry describes machine health at points in time; software inventory describes installed application/package records. Both are device-attributed using the authenticated WebSocket, validated as typed payloads, persisted on the server and queried by the dashboard. A collection failure is distinct from an empty successful sample.

## System telemetry pipeline

1. The agent periodically reads configured host metrics using local collectors and constructs a versioned telemetry sample with collection time and current user/context fields where available.
2. It sends the sample through the active authenticated device socket.
3. The server validates bounds and schema, derives device identity from the connection, and stores the sample with server receipt time.
4. Server query functions expose latest values, time history and summarized ranges; the dashboard presents current status and trends.

Client time is useful as collection metadata but does not establish device liveness. Server receipt timestamps remain the trusted ordering/liveness reference. Retention and payload limits protect storage and ingestion from unbounded histories.

## Software inventory collection algorithm

On Windows the inventory collector combines multiple read-only sources:

1. Enumerate uninstall metadata from HKLM, HKCU and loaded ordinary user hives, across 32-bit and 64-bit registry views as applicable. Skip system components and normalize fields such as display name, version, publisher, architecture, date, install location, package identifier and scope.
2. Run local WinGet list and Chocolatey local-list commands when available, using fixed argument arrays, `shell=False`, bounded time/output and no source installation action.
3. Parse manager output into normalized entries. WinGet parsing uses the aligned terminal table; Chocolatey parsing uses its local package list format.
4. Reconcile a registry record with a WinGet record only where the matching relation is unique in both directions, preventing ambiguous names from collapsing unrelated products. Merge complementary metadata and carry source provenance.
5. Deduplicate by deterministic entry key, cap item/error counts, and preserve detected-manager and collection-error information.
6. Partition records into protocol-safe batches limited by count and serialized byte size. Every batch carries scan identity/index/count metadata; the server assembles a complete scan before replacing the current inventory snapshot.

The collector does not use `Win32_Product`, and it does not install or uninstall anything. LocalSystem's HKCU hive is not treated as an ordinary user inventory; loaded user hives are enumerated where accessible. Manager availability is distinct from a successful empty listing.

## Server storage and dashboard queries

Inventory ingestion binds the scan to the authenticated device. Batch and scan metadata allow the server to distinguish incomplete delivery from a complete empty inventory. Server services expose per-device items, global software summaries, installation lookup, and collection status. The dashboard can request a fresh scan for an online device; a refresh request does not imply that collection has completed until results arrive.

## Failure semantics and boundaries

Registry access denial, WinGet missing/unavailable, Chocolatey timeout and malformed output become structured collection errors. These errors must not be rendered as “no software installed.” Limits on entries, batch sizes and errors bound both endpoint work and server payloads. Inventory is eventually consistent and may omit software that is not represented by supported registry/package-manager sources. Software names and versions are inventory observations, not verified security posture.

## Source map

Agent collector: `software_inventory.py`; request loop and upload framing: `agent.py`; server assembly and query functions: `software_inventory.py`; telemetry queries: `telemetry.py`; schemas/models/migrations define the wire and storage shapes. The server APIs are in `api.py`.
