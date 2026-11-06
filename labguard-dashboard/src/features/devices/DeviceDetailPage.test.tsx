import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { DeviceDetailPage } from "./DeviceDetailPage";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  status: vi.fn(),
  remove: vi.fn(),
  toast: vi.fn(),
  role: { value: "LAB_ADMIN" as string },
}));

vi.mock("./api", () => ({
  devicesApi: { list: mocks.list, status: mocks.status, remove: mocks.remove },
}));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({
    admin: { id: "admin-1", username: "admin", role: mocks.role.value },
  }),
}));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("./SystemTelemetry", () => ({ SystemTelemetry: () => null }));

const device = {
  id: "device-1",
  assigned_name: "Lab PC 01",
  hostname: "LAB-PC-01",
  enrollment_state: "APPROVED",
  enabled: true,
  agent_version: "0.4.0",
};

function CurrentPath() {
  return <output data-testid="path">{useLocation().pathname}</output>;
}

function renderPage(
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  }),
) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/devices/device-1"]}>
          <CurrentPath />
          <Routes>
            <Route path="/devices/:id" element={<DeviceDetailPage />} />
            <Route path="/devices" element={<div>Device list</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  mocks.role.value = "LAB_ADMIN";
  mocks.list.mockResolvedValue([device]);
  mocks.status.mockResolvedValue({
    device_id: device.id,
    agent_state: "OFFLINE",
    network_state: "UNKNOWN",
    last_heartbeat_at: null,
    last_seen_at: null,
    changed_at: new Date().toISOString(),
    connected: false,
  });
  mocks.remove.mockReset();
  mocks.toast.mockReset();
});
afterEach(() => cleanup());

describe("device deletion", () => {
  it("confirms identity and permanence, prevents double submission, then clears and refreshes device data", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["room-layout", "room-1"], {
      assignments: [{ device_id: device.id }],
    });
    let finishDelete!: () => void;
    mocks.remove.mockReturnValue(
      new Promise<void>((resolve) => {
        finishDelete = resolve;
      }),
    );
    renderPage(queryClient);

    await user.click(
      await screen.findByRole("button", { name: /delete device/i }),
    );
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("Lab PC 01");
    expect(dialog.textContent).toContain(device.id);
    expect(dialog.textContent).toMatch(/permanently removes/i);
    expect(dialog.textContent).toMatch(/enrolled and approved again/i);

    const confirm = screen.getByRole("button", { name: /permanently delete/i });
    await user.click(confirm);
    expect(confirm.hasAttribute("disabled")).toBe(true);
    await user.click(confirm);
    expect(mocks.remove).toHaveBeenCalledTimes(1);
    mocks.list.mockResolvedValueOnce([]);
    finishDelete();

    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toContain("/devices"),
    );
    await waitFor(() =>
      expect(queryClient.getQueryData(["devices"])).toEqual([]),
    );
    expect(
      queryClient.getQueryState(["room-layout", "room-1"])?.isInvalidated,
    ).toBe(true);
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.stringMatching(/permanently deleted/i),
    );
  });

  it("does not expose the deletion action to viewers", async () => {
    mocks.role.value = "VIEWER";
    renderPage();
    await screen.findByText("LAB-PC-01");
    expect(screen.queryByRole("button", { name: /delete device/i })).toBeNull();
  });
});
