import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SoftwareCatalogAdmin } from "./SoftwareCatalogAdmin";

const mocks = vi.hoisted(() => ({ catalog: vi.fn(), createCatalogPackage: vi.fn(), approveCatalogPackage: vi.fn(), rejectCatalogPackage: vi.fn(), revokeCatalogPackage: vi.fn(), wingetDiscoveryStatus: vi.fn(), wingetSources: vi.fn(), searchWingetRepository: vi.fn(), importWingetPackage: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { catalog: mocks.catalog, createCatalogPackage: mocks.createCatalogPackage, approveCatalogPackage: mocks.approveCatalogPackage, rejectCatalogPackage: mocks.rejectCatalogPackage, revokeCatalogPackage: mocks.revokeCatalogPackage, wingetDiscoveryStatus: mocks.wingetDiscoveryStatus, wingetSources: mocks.wingetSources, searchWingetRepository: mocks.searchWingetRepository, importWingetPackage: mocks.importWingetPackage } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "SUPER_ADMIN" } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

beforeEach(() => {
  mocks.wingetDiscoveryStatus.mockResolvedValue({ available: true, version: "v1.9.0", error: null });
  mocks.wingetSources.mockResolvedValue({ winget_version: "v1.9.0", sources: [{ name: "winget" }] });
  mocks.importWingetPackage.mockResolvedValue({ created: true, package: { package_id: "Mozilla.Firefox" } });
  mocks.catalog.mockResolvedValue([{
    id: "pkg-1", display_name: "Pending Editor", package_id: "Vendor.Editor", package_manager: "WINGET",
    publisher: "Vendor", description: null, version_policy: "LATEST", approved_version: null,
    supported_scopes: ["MACHINE"], source: "WINGET_COMMUNITY", approved: false, approval_status: "PENDING", created_at: "", approved_at: null,
  }]);
  mocks.approveCatalogPackage.mockResolvedValue({ approved: true });
  mocks.rejectCatalogPackage.mockResolvedValue({ approved: false, approval_status: "REJECTED" });
});
afterEach(() => cleanup());

describe("software package catalog review", () => {
  it("searches catalog entries and approves a package through the admin API", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareCatalogAdmin /></QueryClientProvider>);
    expect(await screen.findByText((_content, element) => element?.tagName === "SPAN" && Boolean(element.textContent?.includes("Vendor.Editor")))).toBeTruthy();
    await user.type(screen.getByLabelText("Search catalog entries"), "Editor");
    await waitFor(() => expect(mocks.catalog).toHaveBeenLastCalledWith(expect.objectContaining({ search: "Editor" })));
    await user.click(screen.getByRole("button", { name: "Approve package" }));
    expect(mocks.approveCatalogPackage).toHaveBeenCalledWith("pkg-1", expect.any(Object));
  });

  it("shows package metadata and lets a Super Admin reject an unapproved package", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareCatalogAdmin /></QueryClientProvider>);
    expect(await screen.findByText(/Review status: PENDING/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(mocks.rejectCatalogPackage).toHaveBeenCalledWith("pkg-1", expect.any(Object));
  });

  it("searches the WinGet repository and adds a result to the pending approval catalog", async () => {
    const user = userEvent.setup();
    mocks.searchWingetRepository.mockResolvedValue({ source: "winget", winget_version: "v1.9.0", results: [{
      name: "Mozilla Firefox", package_id: "Mozilla.Firefox", version: "132.0", source: "winget", catalog_status: null,
    }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareCatalogAdmin /></QueryClientProvider>);
    await user.type(screen.getByLabelText("Search WinGet repository"), "Firefox");
    await user.click(screen.getByRole("button", { name: "Search WinGet repository" }));
    expect(await screen.findByText((_content, element) => element?.tagName === "SPAN" && Boolean(element.textContent?.includes("Mozilla.Firefox")))).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Add for approval" }));
    await waitFor(() => expect(mocks.importWingetPackage).toHaveBeenCalledWith({
      package_id: "Mozilla.Firefox", source: "winget", supported_scopes: ["MACHINE"],
    }));
  });
});
