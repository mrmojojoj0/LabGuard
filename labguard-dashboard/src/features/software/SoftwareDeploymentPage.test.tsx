import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SoftwareDeploymentPage } from "./SoftwareDeploymentPage";

const mocks = vi.hoisted(() => ({ jobs: vi.fn(), devices: vi.fn(), rooms: vi.fn(), layout: vi.fn(), catalog: vi.fn(), search: vi.fn(), details: vi.fn(), createJob: vi.fn(), refresh: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { jobs: mocks.jobs, catalog: mocks.catalog, searchWingetRepository: mocks.search, wingetPackageDetails: mocks.details, createJob: mocks.createJob, refresh: mocks.refresh } }));
vi.mock("../devices/api", () => ({ devicesApi: { list: mocks.devices } }));
vi.mock("../rooms/api", () => ({ roomsApi: { list: mocks.rooms, layout: mocks.layout } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "LAB_ADMIN" } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

beforeEach(() => {
  mocks.jobs.mockResolvedValue({ items: [{
    id: "job-1", device_id: "pc-1", catalog_package_id: null, requested_by: null,
    action: "INSTALL", package_id: "Vendor.Editor", package_manager: "WINGET", requested_version: null,
    installation_scope: "MACHINE", source: "WINGET_COMMUNITY", status: "RUNNING", progress_percent: 40,
    progress_message: "Installing", result_code: null, result_summary: null, error_message: null,
    created_at: "", expires_at: "", dispatched_at: "", accepted_at: "", started_at: "2026-11-06T10:00:00Z", completed_at: null,
  }], total: 1, offset: 0, limit: 100 });
  mocks.devices.mockResolvedValue([
    { id: "pc-1", assigned_name: "Lab PC 01", hostname: "LAB-PC-01", enabled: true, enrollment_state: "APPROVED" },
    { id: "pc-2", assigned_name: "Lab PC 02", hostname: "LAB-PC-02", enabled: true, enrollment_state: "APPROVED" },
  ]);
  mocks.rooms.mockResolvedValue([{ id: "lab-a", name: "Lab A", description: null, grid_rows: 2, grid_columns: 2 }]);
  mocks.layout.mockResolvedValue({ room: { id: "lab-a", name: "Lab A", description: null, grid_rows: 2, grid_columns: 2 }, assignments: [{ device_id: "pc-1", row: 0, column: 0 }, { device_id: "pc-2", row: 0, column: 1 }] });
  mocks.catalog.mockResolvedValue([{
    id: "choco-package", display_name: "Existing Tool", package_id: "vendor-tool", package_manager: "CHOCO",
    publisher: "Vendor", description: null, version_policy: "LATEST", approved_version: null,
    supported_scopes: ["MACHINE"], source: "CHOCO_CONFIGURED", approved: true,
    approval_status: "APPROVED", created_at: "", approved_at: "",
  }]);
  mocks.search.mockResolvedValue({ source: "winget", winget_version: "v1.9", results: [{ name: "Vendor Editor", package_id: "Vendor.Editor", version: "1.2.3", publisher: null, source: "winget" }] });
  mocks.details.mockResolvedValue({ display_name: "Vendor Editor", package_id: "Vendor.Editor", version: "1.2.3", publisher: "Vendor Inc", description: null, source: "winget" });
  mocks.createJob.mockResolvedValue({ id: "job-new", device_id: "pc-1", status: "PENDING" });
  mocks.refresh.mockResolvedValue({});
});
afterEach(() => cleanup());

describe("software deployment monitor", () => {
  it("shows persisted job state, device, progress, and result data", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareDeploymentPage /></QueryClientProvider>);
    expect(await screen.findByText("Software Deployment")).toBeTruthy();
    expect(await screen.findByText("Lab PC 01")).toBeTruthy();
    expect(screen.getByText("RUNNING")).toBeTruthy();
    expect(screen.getByText("40% Installing")).toBeTruthy();
  });

  it("searches WinGet and confirms a direct install for one eligible device", async () => {
    const { fireEvent, waitFor } = await import("@testing-library/react");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareDeploymentPage /></QueryClientProvider>);
    fireEvent.change(await screen.findByLabelText("WinGet search"), { target: { value: "Vendor Editor" } });
    fireEvent.click(screen.getByRole("button", { name: "Search WinGet" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select package" }));
    expect(await screen.findByText(/Vendor Inc/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Lab PC 01"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm installation for 1 PC" }));
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledWith("pc-1", {
      action: "INSTALL", package_manager: "WINGET", package_id: "Vendor.Editor",
      source: "winget", installation_scope: "MACHINE", version: "1.2.3",
    }));
  });

  it("keeps existing approved Chocolatey package installation available", async () => {
    const { fireEvent, waitFor } = await import("@testing-library/react");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareDeploymentPage /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Install Chocolatey package" }));
    fireEvent.click(await screen.findByLabelText("Lab PC 01"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm installation for 1 PC" }));
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledWith("pc-1", {
      action: "INSTALL", catalog_package_id: "choco-package", installation_scope: "MACHINE",
    }));
  });

  it("queues a separate installation job for each selected PC", async () => {
    const { fireEvent, waitFor } = await import("@testing-library/react");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareDeploymentPage /></QueryClientProvider>);
    fireEvent.change(await screen.findByLabelText("WinGet search"), { target: { value: "Vendor Editor" } });
    fireEvent.click(screen.getByRole("button", { name: "Search WinGet" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select package" }));
    await screen.findByText(/Vendor Inc/);
    fireEvent.click(screen.getByLabelText("Lab PC 01"));
    fireEvent.click(screen.getByLabelText("Lab PC 02"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm installation for 2 PCs" }));
    await waitFor(() => {
      expect(mocks.createJob).toHaveBeenCalledTimes(2);
      expect(mocks.createJob).toHaveBeenNthCalledWith(1, "pc-1", expect.objectContaining({ package_id: "Vendor.Editor" }));
      expect(mocks.createJob).toHaveBeenNthCalledWith(2, "pc-2", expect.objectContaining({ package_id: "Vendor.Editor" }));
    });
  });

  it("targets every eligible PC assigned to the selected lab", async () => {
    const { fireEvent, waitFor } = await import("@testing-library/react");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareDeploymentPage /></QueryClientProvider>);
    fireEvent.change(await screen.findByLabelText("WinGet search"), { target: { value: "Vendor Editor" } });
    fireEvent.click(screen.getByRole("button", { name: "Search WinGet" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select package" }));
    await screen.findByText(/Vendor Inc/);
    fireEvent.change(screen.getByLabelText("Deployment target type"), { target: { value: "LAB" } });
    fireEvent.change(screen.getByLabelText("Deployment lab"), { target: { value: "lab-a" } });
    expect(await screen.findByText(/2 of 2 PCs in Lab A/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm installation for 2 PCs" }));
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(2));
  });
});
