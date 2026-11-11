import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DeviceSoftware } from "./DeviceSoftware";

const mocks = vi.hoisted(() => ({ device: vi.fn(), refresh: vi.fn(), catalog: vi.fn(), jobs: vi.fn(), search: vi.fn(), details: vi.fn(), createJob: vi.fn(), toast: vi.fn(), role: { value: "LAB_ADMIN" as string } }));
vi.mock("./api", () => ({ softwareApi: { device: mocks.device, refresh: mocks.refresh, catalog: mocks.catalog, jobs: mocks.jobs, searchWingetRepository: mocks.search, wingetPackageDetails: mocks.details, createJob: mocks.createJob } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: mocks.role.value } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><DeviceSoftware id="device-1" /></QueryClientProvider>);
}
beforeEach(() => {
  mocks.role.value = "LAB_ADMIN";
  mocks.device.mockResolvedValue({
    device_id: "device-1", collection: { status: "COMPLETE", last_attempt_status: "COMPLETE", last_attempt_at: "2026-11-01T00:00:00Z", last_successful_at: "2026-11-01T00:00:00Z", last_complete_at: "2026-11-01T00:00:00Z", started_at: null, completed_at: null, discovered_count: 1, errors: [], stale: false },
    items: [{ id: "row-1", device_id: "device-1", software_key: "a".repeat(64), entry_key: "b".repeat(64), name: "Editor", version: "1.2", publisher: "Acme", architecture: "x64", install_date: null, install_location: null, package_id: null, source: "WINDOWS_REGISTRY", installation_scope: "MACHINE", first_seen_at: "", last_seen_at: "" }],
    total: 1, offset: 0, limit: 100,
  });
  mocks.refresh.mockResolvedValue({ device_id: "device-1", request_id: "r1", status: "requested" });
  mocks.catalog.mockResolvedValue([]);
  mocks.jobs.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 100 });
  mocks.search.mockResolvedValue({ source: "winget", winget_version: "v1.9", results: [{ name: "Vendor Editor", package_id: "Vendor.Editor", version: "1.2.3", publisher: null, source: "winget" }] });
  mocks.details.mockResolvedValue({ display_name: "Vendor Editor", package_id: "Vendor.Editor", version: "1.2.3", publisher: "Vendor Inc", description: null, source: "winget" });
  mocks.createJob.mockResolvedValue({ id: "job-1" });
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

  it("presents partial registry results as successful and distinguishes the last complete collection", async () => {
    mocks.device.mockResolvedValueOnce({
      device_id: "device-1", collection: { status: "PARTIAL", last_attempt_status: "PARTIAL", last_attempt_at: "2026-11-05T00:00:00Z", last_successful_at: "2026-11-05T00:00:00Z", last_complete_at: null, started_at: null, completed_at: null, discovered_count: 1, errors: ["winget_timeout"], stale: false },
      items: [{ id: "row-1", device_id: "device-1", software_key: "a".repeat(64), entry_key: "b".repeat(64), name: "Editor", version: "1.2", publisher: "Acme", architecture: "UNKNOWN", install_date: null, install_location: null, package_id: null, source: "WINDOWS_REGISTRY", installation_scope: "MACHINE", first_seen_at: "", last_seen_at: "" }],
      total: 1, offset: 0, limit: 100,
    });
    renderPanel();
    expect(await screen.findByText("Current partial inventory")).toBeTruthy();
    expect(screen.getByText(/Last successful:/).parentElement?.textContent).not.toContain("Never");
    expect(screen.getByText(/Last complete:/).parentElement?.textContent).toContain("Never");
  });

  it("hides installed applications without an exact supported package identity", async () => {
    renderPanel();
    expect(await screen.findByText("No supported applications on this page")).toBeTruthy();
    expect(screen.queryByText("Editor")).toBeNull();
    expect(screen.queryByText(/Unavailable: no exact supported package identity/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Uninstall" })).toBeNull();
  });

  it("installs a verified WinGet package directly to the current device", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(await screen.findByLabelText("Device WinGet search"), "Vendor Editor");
    await user.click(screen.getByRole("button", { name: "Search WinGet" }));
    await user.click(await screen.findByRole("button", { name: /^Install$/ }));
    expect(await screen.findByText(/Vendor Inc/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Confirm installation" }));
    await vi.waitFor(() => expect(mocks.createJob).toHaveBeenCalledWith("device-1", {
      action: "INSTALL", package_manager: "WINGET", package_id: "Vendor.Editor",
      source: "winget", installation_scope: "MACHINE", version: "1.2.3",
    }));
  });
});
