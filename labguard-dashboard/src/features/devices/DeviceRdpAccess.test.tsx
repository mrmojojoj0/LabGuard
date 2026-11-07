import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DeviceRdpAccess, makeRdpConnectionFile } from "./DeviceRdpAccess";

const mocks = vi.hoisted(() => ({ requestRdp: vi.fn(), rdpRequest: vi.fn(), toast: vi.fn() }));
vi.mock("./api", () => ({ devicesApi: { requestRdp: mocks.requestRdp, rdpRequest: mocks.rdpRequest } }));
vi.mock("../../components/Toast", () => ({ useToast: () => mocks.toast }));

beforeEach(() => {
  mocks.requestRdp.mockResolvedValue({ id: "request-1", device_id: "device-1", hostname: "LAB-PC-01", status: "PENDING", error_code: null, created_at: "2026-11-07T00:00:00Z", expires_at: "2026-11-07T00:02:00Z", access_expires_at: "2099-11-07T01:00:00Z" });
  mocks.rdpRequest.mockResolvedValue({ id: "request-1", device_id: "device-1", hostname: "LAB-PC-01", status: "READY", error_code: null, created_at: "2026-11-07T00:00:00Z", expires_at: "2026-11-07T00:02:00Z", access_expires_at: "2099-11-07T01:00:00Z" });
});
afterEach(() => cleanup());

describe("device Remote Desktop handoff", () => {
  it("generates a minimal RDP file that asks Windows for credentials", () => {
    const file = makeRdpConnectionFile("LAB-PC-01");
    expect(file).toContain("full address:s:LAB-PC-01");
    expect(file).toContain("prompt for credentials:i:1");
    expect(file).not.toMatch(/password|username|gateway/i);
    expect(() => makeRdpConnectionFile("pc\r\nredirectdrives:i:1")).toThrow();
  });

  it("requests endpoint preparation and downloads the file on the admin PC", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:rdp-test");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<QueryClientProvider client={client}><DeviceRdpAccess deviceId="device-1" /></QueryClientProvider>);
    await user.click(screen.getByRole("button", { name: "Request RDP access" }));
    expect((await screen.findByText(/Ready for/)).textContent).toContain("LAB-PC-01");
    await user.click(screen.getByRole("button", { name: "Download Windows RDP file" }));
    expect(mocks.requestRdp).toHaveBeenCalledWith("device-1");
    expect(mocks.rdpRequest).toHaveBeenCalledWith("device-1", "request-1");
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalled();
    expect(screen.getByText(/open it from this PC/)).toBeTruthy();
    createUrl.mockRestore();
    click.mockRestore();
  });
});
