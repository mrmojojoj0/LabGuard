import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SoftwareManagementControls } from "./SoftwareManagementControls";

const mocks = vi.hoisted(() => ({ catalog: vi.fn(), jobs: vi.fn(), createJob: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { catalog: mocks.catalog, jobs: mocks.jobs, createJob: mocks.createJob } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "LAB_ADMIN" } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

beforeEach(() => {
  mocks.createJob.mockClear();
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
  it("requires confirmation before queuing an approved install", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><SoftwareManagementControls id="device-1" items={[]} /></QueryClientProvider>);
    await user.click(await screen.findByRole("button", { name: "Install" }));
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText((_content, element) => element?.tagName === "P" && Boolean(element.textContent?.includes("Target device: device-1")))).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Confirm installation" }));
    expect(mocks.createJob).toHaveBeenCalledWith("device-1", {
      action: "INSTALL", catalog_package_id: "pkg-1", installation_scope: "MACHINE",
    });
  });

  it("requires confirmation before uninstalling a matching package inventory item", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const item = {
      id: "inventory-1", device_id: "device-1", software_key: "a".repeat(64), entry_key: "b".repeat(64),
      name: "Editor", version: "2.0", publisher: "Vendor", architecture: "x64", install_date: null,
      install_location: null, package_id: "Vendor.Editor", source: "WINGET" as const,
      installation_scope: "MACHINE" as const, first_seen_at: "", last_seen_at: "",
    };
    render(<QueryClientProvider client={client}><SoftwareManagementControls id="device-1" items={[item]} /></QueryClientProvider>);
    await user.click(await screen.findByRole("button", { name: "Uninstall" }));
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText(/may affect apps in use/i)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Confirm uninstallation" }));
    expect(mocks.createJob).toHaveBeenCalledWith("device-1", {
      action: "UNINSTALL", catalog_package_id: "pkg-1", inventory_item_id: "inventory-1",
      installation_scope: "MACHINE",
    });
  });
});
