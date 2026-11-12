# Software Discovery and Inventory

## Scope

This report covers how LabGuard discovers installed software and looks up packages in the server's WinGet repository. Inventory discovery is read-only. Repository discovery is metadata search, not installation. The two flows have separate sources, permissions, execution locations, and schemas.

## Endpoint installed-software inventory

The Windows agent reads registry uninstall keys and local package-manager listings, normalizes records, reconciles only unambiguous registry/WinGet duplicates, then sends bounded batches. The server assembles scans and stores a complete result with scan and collection-status metadata. See [Telemetry and Inventory](04-telemetry-inventory.md) for the full collection algorithm. The server never runs a client-side package installation as part of a scan.

## Server WinGet repository discovery pipeline

1. A LAB_ADMIN+ dashboard action calls discovery status/sources/search endpoints. The server owns the WinGet subprocess; the endpoint agent does not service repository search requests.
2. Status reports whether the executable is available, its version, and the identity under which the server process runs. Source listing exposes configured source names without source URLs.
3. Search validates a bounded query and selected source. It runs a fixed `winget search --name` argument vector with `shell=False`, timeout and output bounds. It parses aligned terminal tables rather than relying on undocumented JSON output. Results are capped (100), and a single-source result with no Source column inherits the selected source.
4. Exact package metadata uses `winget show --id <id> --exact` against the fixed source. Package IDs and versions are validated and the output is parsed to structured metadata.
5. Current catalog review status is joined into results where applicable. Search itself does not create authorization or mutate a package record.
6. Direct WinGet installation requests re-fetch exact metadata for the community `winget` source and selected version before creating the existing persistent single-device job. This prevents a stale search result or altered ID from bypassing validation.

## Source and authorization constraints

Only the fixed community `winget` source can flow to the current endpoint execution contract. Other configured sources may be searchable but cannot be imported into a deployable catalog unless client execution supports them. No administrator-supplied executable path, command, URL or shell expression is accepted. Discovery subprocesses use fixed argument arrays and structured sanitized errors.

Legacy catalog records and Super Admin review routes remain for compatibility. Direct WinGet installs need not create an approved catalog record because the server performs exact repository metadata validation at request time. Chocolatey continues to use its existing configured source/catalog path; the WinGet discovery work does not redefine its behavior.

## Failure and trust model

Missing executable, unsupported output, timeout and source errors produce explicit structured failures. Repository output is external data and is revalidated before job creation. A displayed package result is not an approval, and a submitted job is not evidence the endpoint completed installation. The server's WinGet installation and source identity depend on how the server is deployed and must be checked operationally.

## Source map

Server discovery: `winget_discovery.py`; API and authorization: `api.py`; package/catalog/job validation: `software_jobs.py`; dashboard forms and API wrappers: `src/features/software/*`. Endpoint inventory: client `software_inventory.py`. See `docs/LabGuard_v0.7_WinGet_Discovery.md` for milestone notes.
