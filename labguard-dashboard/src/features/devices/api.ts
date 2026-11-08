import { api } from "../../lib/api";
import type {
  Device,
  DeviceProcessRequest,
  ProcessOperation,
  DeviceStatus,
  DeviceTelemetry,
  RdpAccessRequest,
  TelemetrySample,
  TelemetrySummary,
} from "../../lib/types";
export const devicesApi = {
  list: () => api<Device[]>("/devices"),
  status: (id: string) => api<DeviceStatus>(`/devices/${id}/status`),
  remove: (id: string) => api<void>(`/devices/${id}`, { method: "DELETE" }),
  statuses: async (devices: Device[]) =>
    Promise.all(
      devices.map(async (d) => {
        try {
          return await devicesApi.status(d.id);
        } catch {
          return null;
        }
      }),
    ),
  telemetry: (id: string) => api<DeviceTelemetry>(`/devices/${id}/telemetry`),
  telemetryHistory: (id: string, limit = 120) =>
    api<{ device_id: string; samples: TelemetrySample[] }>(
      `/devices/${id}/telemetry/history?limit=${limit}`,
    ),
  telemetrySummary: () => api<TelemetrySummary>("/telemetry/summary"),
  requestRdp: (id: string) => api<RdpAccessRequest>(`/devices/${id}/rdp/requests`, { method: "POST", body: JSON.stringify({}) }),
  rdpRequest: (deviceId: string, requestId: string) =>
    api<RdpAccessRequest>(`/devices/${deviceId}/rdp/requests/${requestId}`),
  requestProcessOperation: (deviceId: string, operation: ProcessOperation,
                            process?: { target_pid: number; target_created_at_us: number }) =>
    api<DeviceProcessRequest>(`/devices/${deviceId}/process-requests`, {
      method: "POST", body: JSON.stringify({ operation, ...(process ?? {}) }),
    }),
  processRequest: (deviceId: string, requestId: string) =>
    api<DeviceProcessRequest>(`/devices/${deviceId}/process-requests/${requestId}`),
};
