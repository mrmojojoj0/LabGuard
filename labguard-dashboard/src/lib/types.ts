export type Role = 'VIEWER' | 'OPERATOR' | 'LAB_ADMIN' | 'SUPER_ADMIN'
export interface Admin { id: string; username: string; role: Role }
export interface Device { id: string; assigned_name: string | null; hostname: string; enrollment_state: string; enabled: boolean; agent_version: string | null }
export interface DeviceStatus { device_id: string; agent_state: string; network_state: string; last_heartbeat_at: string | null; last_seen_at: string | null; changed_at: string }
export interface Room { id: string; name: string; description: string | null; grid_rows: number; grid_columns: number }
export interface Layout { room: Room; assignments: { device_id: string; row: number; column: number }[] }
export interface EnrollmentCode { id: string; code: string; expires_at: string }
export interface AuditEvent { id: string; actor_type: string; actor_id: string | null; action: string; target_type: string; target_id: string | null; result: string; occurred_at: string; metadata: Record<string, unknown> }
export interface ApiErrorShape { error?: { code?: string; message?: string; details?: unknown }; detail?: { code?: string; message?: string; details?: unknown } | string }
