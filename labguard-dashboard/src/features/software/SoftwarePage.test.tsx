import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SoftwarePage } from "./SoftwarePage";

const mocks = vi.hoisted(() => ({ summary: vi.fn(), list: vi.fn(), installations: vi.fn(), devices: vi.fn(), catalog: vi.fn(), createCatalogPackage: vi.fn(), approveCatalogPackage: vi.fn(), revokeCatalogPackage: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { summary: mocks.summary, list: mocks.list, installations: mocks.installations, catalog: mocks.catalog, createCatalogPackage: mocks.createCatalogPackage, approveCatalogPackage: mocks.approveCatalogPackage, revokeCatalogPackage: mocks.revokeCatalogPackage } }));
vi.mock("../devices/api", () => ({ devicesApi: { list: mocks.devices } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "SUPER_ADMIN" } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter><SoftwarePage /></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  mocks.summary.mockResolvedValue({
    unique_applications: 1, total_installations: 2, devices_with_successful_inventory: 2,
    stale_devices: 1, never_reported_devices: 0, partial_devices: 0, collecting_devices: 0,
    most_common: [{ software_key: "a".repeat(64), name: "Editor", publisher: "Acme", installation_count: 2, device_count: 2, source: "WINDOWS_REGISTRY" }],
  });
  mocks.devices.mockResolvedValue([{ id: "pc-1", assigned_name: "Lab PC 01", hostname: "LAB-PC-01" }]);
  mocks.catalog.mockResolvedValue([]);
  mocks.list.mockResolvedValue({
    items: [{ software_key: "a".repeat(64), name: "Editor", publisher: "Acme", installation_count: 2, device_count: 2, source: "WINDOWS_REGISTRY" }],
    total: 1, offset: 0, limit: 50,
  });
  mocks.installations.mockResolvedValue({
    items: [{ id: "row-1", software_key: "a".repeat(64), device_id: "pc-1", device_name: "Lab PC 01", hostname: "LAB-PC-01", name: "Editor", version: "1.2", publisher: "Acme", architecture: "x64", install_date: null, install_location: null, package_id: null, source: "WINDOWS_REGISTRY", installation_scope: "MACHINE", first_seen_at: "", last_seen_at: "" }],
    total: 1, offset: 0, limit: 200,
  });
});
afterEach(() => cleanup());

describe("software inventory page", () => {
  it("renders aggregates, filters results, and opens application installations", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Software Inventory")).toBeTruthy();
    expect(await screen.findByText("2 on 2 devices")).toBeTruthy();
    await user.type(screen.getByPlaceholderText("Search app or publisher"), "Editor");
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ search: "Editor", limit: 50 })));
    await user.selectOptions(screen.getByLabelText("Filter device"), "pc-1");
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ device_id: "pc-1" })));
    await user.click(screen.getAllByRole("button", { name: "Editor" })[0]);
    expect((await screen.findAllByText("Lab PC 01")).length).toBe(2);
  });

  it("shows API errors instead of mock inventory", async () => {
    mocks.list.mockRejectedValueOnce(new Error("server unavailable"));
    renderPage();
    expect(await screen.findByText(/could not be loaded/i)).toBeTruthy();
  });
});
