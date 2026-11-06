import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SoftwareCatalogAdmin } from "./SoftwareCatalogAdmin";

const mocks = vi.hoisted(() => ({ catalog: vi.fn(), createCatalogPackage: vi.fn(), approveCatalogPackage: vi.fn(), revokeCatalogPackage: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ softwareApi: { catalog: mocks.catalog, createCatalogPackage: mocks.createCatalogPackage, approveCatalogPackage: mocks.approveCatalogPackage, revokeCatalogPackage: mocks.revokeCatalogPackage } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ admin: { role: "SUPER_ADMIN" } }) }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

beforeEach(() => {
  mocks.catalog.mockResolvedValue([{
    id: "pkg-1", display_name: "Pending Editor", package_id: "Vendor.Editor", package_manager: "WINGET",
    publisher: "Vendor", description: null, version_policy: "LATEST", approved_version: null,
    supported_scopes: ["MACHINE"], source: "WINGET_COMMUNITY", approved: false, created_at: "", approved_at: null,
  }]);
  mocks.approveCatalogPackage.mockResolvedValue({ approved: true });
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
});
