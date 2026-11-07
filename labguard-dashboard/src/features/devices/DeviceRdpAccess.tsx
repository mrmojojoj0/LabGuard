import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { devicesApi } from "./api";

const HOST_LABEL = "[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?";
const SAFE_HOST = new RegExp(`^(?=.{1,253}$)${HOST_LABEL}(?:\\.${HOST_LABEL})*\\.?$`);

export function makeRdpConnectionFile(hostname: string): string {
  if (!SAFE_HOST.test(hostname)) throw new Error("The target host name is invalid.");
  return [
    "full address:s:" + hostname,
    "prompt for credentials:i:1",
    "enablecredsspsupport:i:1",
    "authentication level:i:2",
    "negotiate security layer:i:1",
    "redirectclipboard:i:1",
    "redirectprinters:i:0",
    "drivestoredirect:s:",
    "",
  ].join("\r\n");
}

function downloadRdp(hostname: string) {
  const contents = makeRdpConnectionFile(hostname);
  const safeFilename = hostname.replace(/[^A-Za-z0-9.-]/g, "_");
  const url = URL.createObjectURL(new Blob([contents], { type: "application/x-rdp" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `LabGuard-${safeFilename}.rdp`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const failureMessage: Record<string, string> = {
  agent_unavailable: "The endpoint agent disconnected before it could prepare RDP.",
  rdp_windows_only: "RDP access can only be prepared on a Windows endpoint.",
  rdp_host_unsupported_edition: "This Windows edition cannot host incoming Remote Desktop connections.",
  rdp_disabled_by_policy: "Windows policy prevents Remote Desktop. LabGuard did not override it.",
  rdp_firewall_unavailable: "Windows Firewall could not be reached.",
  rdp_firewall_configuration_failed: "Windows Firewall rejected the temporary RDP rule.",
  rdp_requires_elevation: "The endpoint agent needs an elevated or LocalSystem token to prepare RDP.",
  rdp_request_expired: "The request expired before the endpoint prepared access.",
  rdp_prepare_failed: "The endpoint could not prepare Remote Desktop.",
};

export function DeviceRdpAccess({ deviceId }: { deviceId: string }) {
  const toast = useToast();
  const [requestId, setRequestId] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const request = useQuery({
    queryKey: ["rdp-request", deviceId, requestId],
    queryFn: () => devicesApi.rdpRequest(deviceId, requestId!),
    enabled: Boolean(requestId),
    refetchInterval: (query) => query.state.data?.status === "PENDING" ? 1000 : false,
    retry: false,
  });
  const create = useMutation({
    mutationFn: () => devicesApi.requestRdp(deviceId),
    onSuccess: (result) => {
      setRequestId(result.id);
      toast("RDP request sent. Waiting for the endpoint.");
    },
    onError: (error: Error) => toast(`RDP request failed. ${error.message}`, "error"),
  });
  useEffect(() => {
    if (request.data?.status !== "READY") return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [request.data?.status]);
  const leaseActive = request.data?.status === "READY" && Date.parse(request.data.access_expires_at) > now;

  return <Panel>
    <PanelTitle>Remote Desktop</PanelTitle>
    <p className="my-3 text-[10px] leading-relaxed text-[var(--color-muted)]">
      Request a temporary 60-minute RDP window. Windows still requires an account and password for this PC. Access is limited to its local subnet on Domain/Private firewall profiles; LabGuard never handles Windows credentials.
    </p>
    {request.isError && <QueryError error={request.error} />}
    {request.data?.status === "PENDING" && <div className="mb-3"><Loading label="Preparing Remote Desktop on the PC…" /></div>}
    {request.data?.status === "FAILED" && <p role="alert" className="mb-3 text-[10px] text-red-700">{failureMessage[request.data.error_code ?? ""] ?? `RDP preparation failed (${request.data.error_code ?? "unknown"}).`}</p>}
    {request.data?.status === "EXPIRED" && <p className="mb-3 text-[10px] text-[var(--color-muted)]">The request expired before RDP became ready. Request access again.</p>}
    {leaseActive && request.data && <div className="mb-3 rounded-lg bg-[var(--color-surface-subtle)] p-3 text-[10px] text-[var(--color-foreground)]">
      <p>Ready for <strong>{request.data.hostname}</strong> until {new Date(request.data.access_expires_at).toLocaleTimeString()}.</p>
      <p className="mt-1 text-[var(--color-muted)]">Download the connection file, then open it from this PC’s Downloads to launch Windows Remote Desktop. Your browser cannot launch desktop apps directly.</p>
    </div>}
    <div className="flex flex-wrap gap-2">
      <Button disabled={create.isPending || request.data?.status === "PENDING"} onClick={() => create.mutate()}>
        {create.isPending ? "Requesting…" : "Request RDP access"}
      </Button>
      {leaseActive && request.data && <Button onClick={() => {
        try { downloadRdp(request.data!.hostname); }
        catch (error) { toast(error instanceof Error ? error.message : "Could not prepare the RDP file.", "error"); }
      }}>Download Windows RDP file</Button>}
    </div>
  </Panel>;
}
