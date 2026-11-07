import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InventoryUninstallAction } from "./InventoryUninstallAction";
import type { SoftwareItem } from "../../lib/types";

const mocks = vi.hoisted(() => ({ jobs: vi.fn(), createJob: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { jobs: mocks.jobs, createJob: mocks.createJob } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "LAB_ADMIN" } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

const item: SoftwareItem = {
  id: "inventory-1", device_id: "device-1", software_key: "a".repeat(64), entry_key: "b".repeat(64),
  name: "Editor", version: "2.0", publisher: "Vendor", architecture: "x64", install_date: null,
  install_location: null, package_id: "Vendor.Editor", source: "WINGET" as const,
  discovery_sources: ["WINGET", "WINDOWS_REGISTRY"],
  installation_scope: "MACHINE" as const, first_seen_at: "", last_seen_at: "",
};
function renderAction() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><InventoryUninstallAction deviceId="device-1" item={item} /></QueryClientProvider>);
}
beforeEach(() => {
  mocks.jobs.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 100 });
  mocks.createJob.mockResolvedValue({ id: "job-1" });
  mocks.toast.mockReset();
});
afterEach(() => cleanup());

describe("installed row uninstall action", () => {
  it("submits only after confirmation using the exact inventory row", async () => {
    const user = userEvent.setup();
    renderAction();
    await user.click(await screen.findByRole("button", { name: "Uninstall" }));
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText(/official package manager/i)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Confirm uninstallation" }));
    expect(mocks.createJob).toHaveBeenCalledWith("device-1", {
      action: "UNINSTALL", inventory_item_id: "inventory-1",
    });
  });

  it("does not offer uninstall when the package mapping or scope is unsupported", async () => {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}><InventoryUninstallAction deviceId="device-1" item={{ ...item, source: "WINDOWS_REGISTRY" }} /></QueryClientProvider>);
    expect(await screen.findByText(/Unavailable: no exact supported package identity/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Uninstall" })).toBeNull();
  });

  it("does not offer uninstall when WinGet inventory scope is unknown", async () => {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}><InventoryUninstallAction deviceId="device-1" item={{ ...item, installation_scope: "UNKNOWN" }} /></QueryClientProvider>);
    expect(await screen.findByText(/Unavailable: no exact supported package identity/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Uninstall" })).toBeNull();
  });

  it("shows job status and result for the submitted row and invalidates inventory after verified removal", async () => {
    const user = userEvent.setup();
    mocks.jobs.mockResolvedValue({ items: [{ id: "job-1", action: "UNINSTALL", package_id: "Vendor.Editor",
      status: "SUCCEEDED", progress_percent: 100, progress_message: "Verified absent", result_summary: "Removed and verified",
      result_code: "verified_success", error_message: null }], total: 1, offset: 0, limit: 100 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><InventoryUninstallAction deviceId="device-1" item={item} /></QueryClientProvider>);
    await user.click(await screen.findByRole("button", { name: "Uninstall" }));
    await user.click(screen.getByRole("button", { name: "Confirm uninstallation" }));
    expect(await screen.findByText(/SUCCEEDED: 100% Verified absent/)).toBeTruthy();
    expect(mocks.toast).toHaveBeenCalledWith("Uninstallation verified; installed software inventory refreshed.");
  });

  it("surfaces uninstall job errors inline", async () => {
    const user = userEvent.setup();
    mocks.jobs.mockResolvedValue({ items: [{ id: "job-1", action: "UNINSTALL", package_id: "Vendor.Editor",
      status: "FAILED", progress_percent: 90, progress_message: "", result_summary: "",
      result_code: "package_manager_exit_1", error_message: "Uninstaller could not run silently" }], total: 1, offset: 0, limit: 100 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><InventoryUninstallAction deviceId="device-1" item={item} /></QueryClientProvider>);
    await user.click(await screen.findByRole("button", { name: "Uninstall" }));
    await user.click(screen.getByRole("button", { name: "Confirm uninstallation" }));
    expect(await screen.findByText(/FAILED: 90% Uninstaller could not run silently/)).toBeTruthy();
  });
});
