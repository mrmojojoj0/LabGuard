import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NetworkMonitoringPage } from "./NetworkMonitoringPage";

const mocks = vi.hoisted(() => ({ connections: vi.fn(), events: vi.fn() }));
vi.mock("./api", () => ({ networkApi: { connections: mocks.connections, events: mocks.events } }));

beforeEach(() => {
  mocks.connections.mockResolvedValue({ lookups_enabled: true, public_ip_count: 1, connections: [{
    device_id: "device-1", device_name: "LAB-PC-01", remote_ip: "8.8.8.8", remote_port: 443,
    local_port: 50120, direction: "OUTGOING", protocol: "TCP", interface: "Ethernet",
    state: "ESTABLISHED", observed_at: "2026-11-10T12:00:00Z", organization: { as_name: "Google", asn: "AS15169" },
  }] });
  mocks.events.mockImplementation(async (showFullInfo: boolean) => ({
    events: [{ id: "event-1", device_id: "device-1", device_name: "LAB-PC-01", log_generation: "generation-1",
      event_record_id: 42, event_id: 5156, event_time: "2026-11-10T12:01:00Z", event_kind: "CONNECTION_ALLOWED",
      direction: "OUTGOING", protocol: "TCP", protocol_number: 6, source_ip: "192.168.1.10", source_port: 50200,
      destination_ip: "8.8.8.8", destination_port: 443, remote_ip: "8.8.8.8", process_id: 1234,
      process_path: "curl.exe", source: "WFP_EVENT", organization: { as_name: "Google" } }],
    total: 1, limit: 100, offset: 0, monitoring: [{ device_id: "device-1", device_name: "LAB-PC-01",
      status: "ACTIVE", gap_reason: null, error_code: null, cursor_record_id: 42,
      updated_at: "2026-11-10T12:01:00Z", stale: false }], show_full_info: showFullInfo, lookups_enabled: true,
  }));
});
afterEach(() => cleanup());

describe("network monitoring", () => {
  it("shows historical WFP connections and hides endpoint details until Show Full Info", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><NetworkMonitoringPage /></QueryClientProvider>);

    expect(await screen.findByText("connection allowed")).toBeTruthy();
    expect(screen.queryByText(/192\.168\.1\.10/)).toBeNull();
    expect(screen.queryByText(/Ethernet/)).toBeNull();
    expect(screen.queryByText("50120")).toBeNull();
    expect(screen.getByText(/ACTIVE/)).toBeTruthy();

    await user.click(screen.getByLabelText("Show Full Info"));
    expect(await screen.findByText(/192\.168\.1\.10/)).toBeTruthy();
    expect(screen.getByText(/Ethernet/)).toBeTruthy();
    expect(mocks.events).toHaveBeenCalledWith(true, 0);
  });
});
