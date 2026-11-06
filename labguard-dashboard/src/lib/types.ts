export type Role = "VIEWER" | "OPERATOR" | "LAB_ADMIN" | "SUPER_ADMIN";
export interface Admin {
  id: string;
  username: string;
  role: Role;
}
export interface Device {
  id: string;
  assigned_name: string | null;
  hostname: string;
  enrollment_state: string;
  enabled: boolean;
  agent_version: string | null;
}
export interface DeviceStatus {
  device_id: string;
  agent_state: string;
  network_state: string;
  last_heartbeat_at: string | null;
  last_seen_at: string | null;
  changed_at: string;
  connected: boolean;
}
export interface TelemetryPartition {
  device: string;
  mountpoint: string;
  filesystem: string | null;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  utilization_percent: number;
}
export interface TelemetryInterface {
  name: string;
  status: "UP" | "DOWN" | "UNKNOWN";
  mac_address: string | null;
  ipv4_addresses: string[];
  ipv6_addresses: string[];
  speed_mbps: number | null;
}
export interface TelemetrySnapshot {
  collected_at: string;
  received_at: string;
  cpu: {
    processor_name: string | null;
    logical_processors: number;
    physical_cores: number | null;
    utilization_percent: number;
  };
  memory: {
    total_bytes: number;
    used_bytes: number;
    available_bytes: number;
    utilization_percent: number;
  };
  storage_partitions: TelemetryPartition[];
  operating_system: {
    edition: string | null;
    version: string | null;
    build_number: string | null;
    architecture: string;
    hostname: string;
  };
  boot_time: string;
  uptime_seconds: number;
  network_interfaces: TelemetryInterface[];
}
export interface DeviceTelemetry {
  device_id: string;
  snapshot: TelemetrySnapshot | null;
  stale: boolean;
  stale_after_seconds: number;
}
export interface TelemetrySample {
  collected_at: string;
  received_at: string;
  cpu_percent: number;
  memory_percent: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
  disk_percent: number | null;
  disk_used_bytes: number;
  disk_total_bytes: number;
}
export interface TelemetrySummary {
  reporting_devices: number;
  stale_devices: number;
  average_cpu_percent: number | null;
  average_memory_percent: number | null;
  average_disk_percent: number | null;
}
export interface SoftwareItem {
  id: string;
  device_id: string;
  software_key: string;
  entry_key: string;
  name: string;
  version: string | null;
  publisher: string | null;
  architecture: string;
  install_date: string | null;
  install_location: string | null;
  package_id: string | null;
  source: "WINDOWS_REGISTRY" | "WINGET" | "CHOCO";
  installation_scope: "MACHINE" | "USER" | "UNKNOWN";
  first_seen_at: string;
  last_seen_at: string;
  device_name?: string | null;
  hostname?: string | null;
}
export interface SoftwareCollectionStatus {
  collection_id?: string;
  request_id?: string | null;
  status: "NEVER" | "IN_PROGRESS" | "COMPLETE" | "PARTIAL" | "FAILED" | "UNCHANGED";
  started_at: string | null;
  last_attempt_at?: string | null;
  last_attempt_status?: string;
  completed_at: string | null;
  last_successful_at: string | null;
  last_complete_at?: string | null;
  discovered_count: number;
  errors: string[];
  stale?: boolean;
}
export interface SoftwareSummary {
  unique_applications: number;
  total_installations: number;
  devices_with_successful_inventory: number;
  stale_devices: number;
  never_reported_devices: number;
  partial_devices: number;
  collecting_devices: number;
  most_common: Array<{
    software_key: string;
    name: string;
    publisher: string | null;
    installation_count: number;
    device_count: number;
    source: string;
  }>;
}
export interface SoftwarePageResult {
  items: SoftwareItem[];
  total: number;
  offset: number;
  limit: number;
  status?: SoftwareCollectionStatus;
}
export interface SoftwareAggregate {
  software_key: string;
  name: string;
  publisher: string | null;
  installation_count: number;
  device_count: number;
  source: string;
}
export interface SoftwareAggregatePage {
  items: SoftwareAggregate[];
  total: number;
  offset: number;
  limit: number;
}
export interface SoftwareCatalogPackage {
  id: string;
  display_name: string;
  package_id: string;
  package_manager: "WINGET" | "CHOCO";
  publisher: string | null;
  description: string | null;
  version_policy: "LATEST" | "PINNED" | "SELECTABLE";
  approved_version: string | null;
  supported_scopes: Array<"MACHINE" | "USER">;
  source: string;
  approved: boolean;
  approval_status: "PENDING" | "APPROVED" | "REJECTED" | "REVOKED";
  created_at: string;
  approved_at: string | null;
}
export interface WingetDiscoveryStatus {
  available: boolean;
  version: string | null;
  execution_identity: string;
  error: { code: string; message: string } | null;
}
export interface WingetDiscoveryResult {
  name: string;
  package_id: string;
  version: string | null;
  source: string;
  catalog_status: SoftwareCatalogPackage["approval_status"] | null;
}
export interface SoftwareJob {
  id: string;
  device_id: string;
  catalog_package_id: string | null;
  requested_by: string | null;
  action: "INSTALL" | "UNINSTALL";
  package_id: string;
  package_manager: "WINGET" | "CHOCO";
  requested_version: string | null;
  installation_scope: "MACHINE" | "USER";
  source: string;
  status: "PENDING" | "DISPATCHED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "EXPIRED";
  progress_percent: number;
  progress_message: string | null;
  result_code: string | null;
  result_summary: string | null;
  error_message: string | null;
  created_at: string;
  expires_at: string;
  dispatched_at: string | null;
  accepted_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}
export interface SoftwareJobsPage {
  items: SoftwareJob[];
  total: number;
  offset: number;
  limit: number;
}
export interface Room {
  id: string;
  name: string;
  description: string | null;
  grid_rows: number;
  grid_columns: number;
}
export interface Layout {
  room: Room;
  assignments: { device_id: string; row: number; column: number }[];
}
export interface EnrollmentCode {
  id: string;
  code: string;
  expires_at: string;
}
export interface AuditEvent {
  id: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  result: string;
  occurred_at: string;
  metadata: Record<string, unknown>;
}
export interface ApiErrorShape {
  error?: { code?: string; message?: string; details?: unknown };
  detail?: { code?: string; message?: string; details?: unknown } | string;
}
