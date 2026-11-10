import { api } from "../../lib/api";
import type { NetworkConnectionsResponse, WfpNetworkEventsResponse } from "../../lib/types";

export const networkApi = {
  connections: () => api<NetworkConnectionsResponse>("/network/connections"),
  events: (showFullInfo: boolean, offset = 0, deviceId?: string) => {
    const deviceFilter = deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : "";
    return api<WfpNetworkEventsResponse>(`/network/events?limit=100&offset=${offset}&since_seconds=120&show_full_info=${showFullInfo}${deviceFilter}`);
  },
};
