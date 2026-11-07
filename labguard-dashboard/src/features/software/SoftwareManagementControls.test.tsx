import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SoftwareManagementControls } from "./SoftwareManagementControls";

const mocks = vi.hoisted(() => ({ catalog: vi.fn(), jobs: vi.fn(), createJob: vi.fn(), wingetSources: vi.fn(), searchWingetRepository: vi.fn(), importWingetPackage: vi.fn(), role: "LAB_ADMIN" as string, toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { catalog: mocks.catalog, jobs: mocks.jobs, createJob: mocks.createJob, wingetSources: mocks.wingetSources, searchWingetRepository: mocks.searchWingetRepository, importWingetPackage: mocks.importWingetPackage } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: mocks.role } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

beforeEach(() => {
  mocks.role = "LAB_ADMIN";
  mocks.createJob.mockClear();
  mocks.searchWingetRepository.mockReset();
  mocks.importWingetPackage.mockReset();
  mocks.wingetSources.mockResolvedValue({ winget_version: "v1.9.0", sources: [{ name: "winget" }] });
  mocks.catalog.mockResolvedValue([{
    id: "pkg-1", display_name: "Editor", package_id: "Vendor.Editor", package_manager: "WINGET",
    publisher: "Vendor", description: null, version_policy: "LATEST", approved_version: null,
    supported_scopes: ["MACHINE"], source: "WINGET_COMMUNITY", approved: true,
    created_at: "", approved_at: "",
  }]);
  mocks.jobs.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 100 });
  mocks.createJob.mockResolvedValue({ id: "job-1" });
});
afterEach(() => cleanup());

describe("device software management", () => {
  it("keeps approved-catalog search separate from live WinGet repository search and imports discoveries", async () => {
    const user = userEvent.setup();
    mocks.role = "SUPER_ADMIN";
    mocks.searchWingetRepository.mockResolvedValue({ source: "winget", winget_version: "v1.9.0", results: [{
      name: "Firefox", package_id: "Mozilla.Firefox", version: "132.0", source: "winget", catalog_status: null,
    }] });
    mocks.importWingetPackage.mockResolvedValue({ created: true, package: { package_id: "Mozilla.Firefox", approval_status: "PENDING" } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareManagementControls id="device-1" /></QueryClientProvider>);

    await user.type(screen.getByPlaceholderText("Search approved packages"), "firefox");
    await waitFor(() => expect(mocks.catalog).toHaveBeenLastCalledWith(expect.objectContaining({ search: "firefox", approved: true })));
    expect(mocks.searchWingetRepository).not.toHaveBeenCalled();
    const catalogCallsBeforeDiscovery = mocks.catalog.mock.calls.length;

    await user.type(screen.getByLabelText("WinGet repository search text"), "Firefox");
    await user.click(screen.getByRole("button", { name: "Search WinGet Repository" }));
    expect(await screen.findByText((_content, element) => element?.tagName === "SPAN" && Boolean(element.textContent?.includes("Mozilla.Firefox")))).toBeTruthy();
    expect(mocks.searchWingetRepository).toHaveBeenCalledWith("Firefox", "winget");
    expect(mocks.catalog).toHaveBeenCalledTimes(catalogCallsBeforeDiscovery);

    await user.click(screen.getByRole("button", { name: "Add for approval" }));
    await waitFor(() => expect(mocks.importWingetPackage).toHaveBeenCalledWith({
      package_id: "Mozilla.Firefox", source: "winget", supported_scopes: ["MACHINE"],
    }));
  });

  it("requires confirmation before queuing an approved install", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareManagementControls id="device-1" /></QueryClientProvider>);
    await user.click(await screen.findByRole("button", { name: "Install" }));
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText((_content, element) => element?.tagName === "P" && Boolean(element.textContent?.includes("Target device: device-1")))).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Confirm installation" }));
    expect(mocks.createJob).toHaveBeenCalledWith("device-1", {
      action: "INSTALL", catalog_package_id: "pkg-1", installation_scope: "MACHINE",
    });
  });

});
