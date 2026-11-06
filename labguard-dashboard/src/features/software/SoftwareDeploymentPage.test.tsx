import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SoftwareDeploymentPage } from "./SoftwareDeploymentPage";

const mocks = vi.hoisted(() => ({ jobs: vi.fn(), devices: vi.fn(), catalog: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { jobs: mocks.jobs, catalog: mocks.catalog } }));
vi.mock("../devices/api", () => ({ devicesApi: { list: mocks.devices } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "VIEWER" } }) }));

beforeEach(() => {
  mocks.jobs.mockResolvedValue({ items: [{
    id: "job-1", device_id: "pc-1", catalog_package_id: null, requested_by: null,
    action: "INSTALL", package_id: "Vendor.Editor", package_manager: "WINGET", requested_version: null,
    installation_scope: "MACHINE", source: "WINGET_COMMUNITY", status: "RUNNING", progress_percent: 40,
    progress_message: "Installing", result_code: null, result_summary: null, error_message: null,
    created_at: "", expires_at: "", dispatched_at: "", accepted_at: "", started_at: "2026-11-06T10:00:00Z", completed_at: null,
  }], total: 1, offset: 0, limit: 100 });
  mocks.devices.mockResolvedValue([{ id: "pc-1", assigned_name: "Lab PC 01", hostname: "LAB-PC-01" }]);
  mocks.catalog.mockResolvedValue([]);
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
});
