import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DeviceSoftware } from "./DeviceSoftware";

const mocks = vi.hoisted(() => ({ device: vi.fn(), refresh: vi.fn(), toast: vi.fn(), role: { value: "LAB_ADMIN" as string } }));
vi.mock("./api", () => ({ softwareApi: { device: mocks.device, refresh: mocks.refresh } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: mocks.role.value } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><DeviceSoftware id="device-1" /></QueryClientProvider>);
}
beforeEach(() => {
  mocks.role.value = "LAB_ADMIN";
  mocks.device.mockResolvedValue({
    device_id: "device-1", collection: { status: "COMPLETE", last_successful_at: "2026-11-01T00:00:00Z", started_at: null, completed_at: null, discovered_count: 1, errors: [], stale: false },
    items: [{ id: "row-1", device_id: "device-1", software_key: "a".repeat(64), entry_key: "b".repeat(64), name: "Editor", version: "1.2", publisher: "Acme", architecture: "x64", install_date: null, install_location: null, package_id: null, source: "WINDOWS_REGISTRY", installation_scope: "MACHINE", first_seen_at: "", last_seen_at: "" }],
    total: 1, offset: 0, limit: 100,
  });
  mocks.refresh.mockResolvedValue({ device_id: "device-1", request_id: "r1", status: "requested" });
  mocks.toast.mockReset();
});
afterEach(() => cleanup());

describe("device software inventory", () => {
  it("shows real entries and lets an authorized administrator request refresh", async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(await screen.findByText("Editor")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /refresh inventory/i }));
    expect(mocks.refresh).toHaveBeenCalledWith("device-1");
    expect(mocks.toast).toHaveBeenCalledWith("Inventory refresh requested.");
  });

  it("does not show refresh controls to viewers", async () => {
    mocks.role.value = "VIEWER";
    renderPanel();
    await screen.findByText("Editor");
    expect(screen.queryByRole("button", { name: /refresh inventory/i })).toBeNull();
  });
});
