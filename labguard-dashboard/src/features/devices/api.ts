import { api } from '../../lib/api'
import type { Device, DeviceStatus } from '../../lib/types'
export const devicesApi = {
  list: () => api<Device[]>('/devices'),
  status: (id: string) => api<DeviceStatus>(`/devices/${id}/status`),
  statuses: async (devices: Device[]) => Promise.all(devices.map(async d => { try { return await devicesApi.status(d.id) } catch { return null } })),
}
