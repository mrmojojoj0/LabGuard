import { api, json } from "../../lib/api";
import type { SoftwareAggregatePage, SoftwareCatalogPackage, SoftwareCollectionStatus, SoftwareJobsPage, SoftwarePageResult, SoftwareSummary, SoftwareJob, WingetDiscoveryResult, WingetDiscoveryStatus } from "../../lib/types";

export interface SoftwareFilters {
  search?: string;
  publisher?: string;
  source?: string;
  installation_scope?: string;
  version?: string;
  device_id?: string;
  offset?: number;
  limit?: number;
}

function query(filters: SoftwareFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params.size ? `?${params.toString()}` : "";
}

export const softwareApi = {
  summary: () => api<SoftwareSummary>("/software/summary"),
  list: (filters: SoftwareFilters = {}) =>
    api<SoftwareAggregatePage>(`/software${query(filters)}`),
  device: (id: string, filters: SoftwareFilters = {}) =>
    api<SoftwarePageResult & { device_id: string; collection: SoftwareCollectionStatus }>(
      `/devices/${id}/software${query(filters)}`,
    ),
  installations: (key: string) =>
    api<SoftwarePageResult>(`/software/${key}/installations`),
  refresh: (id: string) =>
    api<{ device_id: string; request_id: string; status: string }>(
      `/devices/${id}/software/refresh`,
      json("POST", {}),
    ),
  catalog: (filters: { search?: string; package_manager?: string; approved?: boolean } = {}) =>
    api<SoftwareCatalogPackage[]>(`/software/catalog${query(filters)}`),
  wingetDiscoveryStatus: () => api<WingetDiscoveryStatus>("/software/discovery/status"),
  wingetSources: () => api<{ winget_version: string; sources: Array<{ name: string }> }>("/software/discovery/sources"),
  searchWingetRepository: (search: string, source = "winget") =>
    api<{ source: string; winget_version: string; results: WingetDiscoveryResult[] }>(
      `/software/discovery/search?query=${encodeURIComponent(search)}&source=${encodeURIComponent(source)}`,
    ),
  importWingetPackage: (body: { package_id: string; source: string; supported_scopes: Array<"MACHINE" | "USER"> }) =>
    api<{ package: SoftwareCatalogPackage; created: boolean }>("/software/discovery/import", json("POST", body)),
  createCatalogPackage: (body: {
    display_name: string; package_id: string; package_manager: "WINGET" | "CHOCO";
    publisher?: string; description?: string; version_policy: "LATEST" | "PINNED" | "SELECTABLE";
    approved_version?: string; supported_scopes: Array<"MACHINE" | "USER">;
  }) => api<SoftwareCatalogPackage>("/software/catalog", json("POST", body)),
  approveCatalogPackage: (id: string) =>
    api<SoftwareCatalogPackage>(`/software/catalog/${id}/approve`, json("POST", {})),
  revokeCatalogPackage: (id: string) =>
    api<SoftwareCatalogPackage>(`/software/catalog/${id}/revoke`, json("POST", {})),
  rejectCatalogPackage: (id: string) =>
    api<SoftwareCatalogPackage>(`/software/catalog/${id}/reject`, json("POST", {})),
  createJob: (deviceId: string, body: {
    action: "INSTALL" | "UNINSTALL"; catalog_package_id: string;
    installation_scope?: "MACHINE" | "USER"; version?: string;
    inventory_item_id?: string; expires_in_seconds?: number;
  }) => api<SoftwareJob>(`/devices/${deviceId}/software/jobs`, json("POST", body)),
  jobs: (deviceId?: string) => api<SoftwareJobsPage>(
    deviceId ? `/devices/${deviceId}/software/jobs?limit=100` : "/software/jobs?limit=100",
  ),
};
