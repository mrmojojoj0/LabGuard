import { api } from '../../lib/api'
import type { Device, DeviceStatus, DeviceTelemetry, TelemetrySample, TelemetrySummary } from '../../lib/types'
export const devicesApi = {
  list: () => api<Device[]>('/devices'),
  status: (id: string) => api<DeviceStatus>(`/devices/${id}/status`),
  statuses: async (devices: Device[]) => Promise.all(devices.map(async d => { try { return await devicesApi.status(d.id) } catch { return null } })),
  telemetry: (id: string) => api<DeviceTelemetry>(`/devices/${id}/telemetry`),
  telemetryHistory: (id: string, limit = 120) => api<{ device_id: string; samples: TelemetrySample[] }>(`/devices/${id}/telemetry/history?limit=${limit}`),
  telemetrySummary: () => api<TelemetrySummary>('/telemetry/summary'),
}
