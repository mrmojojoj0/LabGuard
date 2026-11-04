export type Role = 'VIEWER' | 'OPERATOR' | 'LAB_ADMIN' | 'SUPER_ADMIN'
export interface Admin { id: string; username: string; role: Role }
export interface Device { id: string; assigned_name: string | null; hostname: string; enrollment_state: string; enabled: boolean; agent_version: string | null }
export interface DeviceStatus { device_id: string; agent_state: string; network_state: string; last_heartbeat_at: string | null; last_seen_at: string | null; changed_at: string; connected: boolean }
export interface TelemetryPartition { device: string; mountpoint: string; filesystem: string | null; total_bytes: number; used_bytes: number; free_bytes: number; utilization_percent: number }
export interface TelemetryInterface { name: string; status: 'UP' | 'DOWN' | 'UNKNOWN'; mac_address: string | null; ipv4_addresses: string[]; ipv6_addresses: string[]; speed_mbps: number | null }
export interface TelemetrySnapshot { collected_at: string; received_at: string; cpu: { processor_name: string | null; logical_processors: number; physical_cores: number | null; utilization_percent: number }; memory: { total_bytes: number; used_bytes: number; available_bytes: number; utilization_percent: number }; storage_partitions: TelemetryPartition[]; operating_system: { edition: string | null; version: string | null; build_number: string | null; architecture: string; hostname: string }; boot_time: string; uptime_seconds: number; network_interfaces: TelemetryInterface[] }
export interface DeviceTelemetry { device_id: string; snapshot: TelemetrySnapshot | null; stale: boolean; stale_after_seconds: number }
export interface TelemetrySample { collected_at: string; received_at: string; cpu_percent: number; memory_percent: number; memory_used_bytes: number; memory_total_bytes: number; disk_percent: number | null; disk_used_bytes: number; disk_total_bytes: number }
export interface TelemetrySummary { reporting_devices: number; stale_devices: number; average_cpu_percent: number | null; average_memory_percent: number | null; average_disk_percent: number | null }
export interface Room { id: string; name: string; description: string | null; grid_rows: number; grid_columns: number }
export interface Layout { room: Room; assignments: { device_id: string; row: number; column: number }[] }
export interface EnrollmentCode { id: string; code: string; expires_at: string }
export interface AuditEvent { id: string; actor_type: string; actor_id: string | null; action: string; target_type: string; target_id: string | null; result: string; occurred_at: string; metadata: Record<string, unknown> }
export interface ApiErrorShape { error?: { code?: string; message?: string; details?: unknown }; detail?: { code?: string; message?: string; details?: unknown } | string }
