import { useEffect, useState } from "react";
import { Camera, Image, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Empty, PageHeader, Panel, QueryError, Skeleton, StatusBadge } from "../../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { devicesApi } from "./api";
import type { ScreenshotCapture } from "../../lib/types";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function screenshotError(code: string | null): string | null {
  if (!code) return null;
  const messages: Record<string, string> = {
    no_active_session: "No active Windows console session was found.",
    desktop_access_denied: "Windows denied access to the desktop or capture runtime.",
    required_windows_privilege_missing: "The agent service is missing a required Windows privilege. Reinstall it as LocalSystem.",
    python_runtime_unavailable: "The agent's Python runtime could not be started in the desktop session.",
    windows_capture_dependencies_missing: "The client is missing a required Windows capture dependency. Rebuild and reinstall it.",
    screenshot_dependency_missing: "Pillow is missing from the client environment. Rebuild and reinstall the client dependencies.",
    desktop_capture_failed: "Windows could not capture the active desktop. Confirm a user is signed in at the console.",
    screenshot_temp_conflict: "A temporary capture file already exists. Retry the request.",
    screenshot_temp_unavailable: "Windows could not write the temporary image.",
    screenshot_output_unavailable: "The capture helper did not leave a readable image for the service.",
    capture_timeout: "Screen capture took too long and was stopped.",
    capture_internal_error: "The agent encountered an unexpected capture error. Check C:\\ProgramData\\LabGuard\\labguard-agent.log after updating the client.",
  };
  return messages[code] ?? code.replaceAll("_", " ");
}

function useImage(capture: ScreenshotCapture) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (capture.status !== "READY") return;
    let current: string | null = null;
    void fetch(`${baseUrl}/api/v1/screenshots/${capture.id}/image`, { credentials: "include" })
      .then((response) => response.ok ? response.blob() : Promise.reject())
      .then((blob) => {
        current = URL.createObjectURL(blob);
        setUrl(current);
      }).catch(() => setUrl(null));
    return () => { if (current) URL.revokeObjectURL(current); };
  }, [capture.id, capture.status]);
  return url;
}

function CaptureCard({ capture, onDelete, deleting }: { capture: ScreenshotCapture; onDelete: () => void; deleting: boolean }) {
  const imageUrl = useImage(capture);
  return (
    <article className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="aspect-video bg-[var(--color-surface-subtle)]">
        {imageUrl ? <a href={imageUrl} target="_blank" rel="noreferrer"><img className="h-full w-full object-contain" src={imageUrl} alt={`Screen capture from ${capture.device_name}`} /></a>
          : <div className="grid h-full place-items-center text-[var(--color-muted)]"><Image size={28} /></div>}
      </div>
      <div className="space-y-2 p-3">
        <div className="flex items-center justify-between gap-2"><strong className="truncate text-[11px]">{capture.device_name}</strong><StatusBadge value={capture.status} /></div>
        <p className="m-0 text-[9px] leading-relaxed text-[var(--color-muted)]">
          {capture.captured_at ? `Captured ${new Date(capture.captured_at).toLocaleString()}` : `Requested ${new Date(capture.created_at).toLocaleString()}`}
          {capture.status === "READY" && ` · Expires ${new Date(capture.expires_at).toLocaleString()}`}
          {capture.error_code && ` · ${screenshotError(capture.error_code)}`}
        </p>
        <Button className="min-h-8 border-red-200 px-2 text-[9px] text-red-700 dark:border-red-900 dark:text-red-300" disabled={deleting} onClick={() => {
          if (window.confirm(`Permanently delete the screenshot from ${capture.device_name}?`)) onDelete();
        }}><Trash2 size={13} /> Delete capture</Button>
      </div>
    </article>
  );
}

export function ScreenshotMonitoringPage() {
  const { admin } = useAuth();
  const queryClient = useQueryClient();
  const captures = useQuery({ queryKey: ["screenshots"], queryFn: () => devicesApi.screenshots(),
    refetchInterval: (query) => query.state.data?.some((item) => item.status === "PENDING") ? 1500 : 10_000 });
  const remove = useMutation({ mutationFn: devicesApi.deleteScreenshot,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["screenshots"] }) });
  if (admin?.role !== "LAB_ADMIN" && admin?.role !== "SUPER_ADMIN") {
    return <><PageHeader eyebrow="MONITORING" title="Screenshot Monitoring" /><Panel><p className="m-0 text-xs text-[var(--color-muted)]">LAB_ADMIN access is required to request or view captures.</p></Panel></>;
  }
  return <>
    <PageHeader eyebrow="MONITORING" title="Screenshot Monitoring" description="Review and delete captures requested from individual device dashboards. Captures are kept for 24 hours." />
    {captures.isError && <QueryError error={captures.error} />}
    <Panel>
      <div className="mb-4 flex items-center justify-between"><h2 className="m-0 text-[13px] font-bold">Recent captures</h2><span className="text-[9px] text-[var(--color-muted)]">Auto-delete after 24 hours</span></div>
      {captures.isLoading ? <Skeleton rows={4} /> : captures.data?.length ?
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{captures.data.map((capture) => <CaptureCard key={capture.id} capture={capture} deleting={remove.isPending} onDelete={() => remove.mutate(capture.id)} />)}</div>
        : <Empty title="No screenshots captured" detail="Request a capture from a device's Screenshots tab." />}
    </Panel>
  </>;
}

export function DeviceScreenshotPanel({ deviceId }: { deviceId: string }) {
  const { admin } = useAuth();
  const queryClient = useQueryClient();
  const allowed = admin?.role === "LAB_ADMIN" || admin?.role === "SUPER_ADMIN";
  const captures = useQuery({ queryKey: ["screenshots", deviceId], queryFn: () => devicesApi.screenshots(deviceId),
    refetchInterval: (query) => query.state.data?.some((item) => item.status === "PENDING") ? 1500 : 10_000,
    enabled: allowed });
  const request = useMutation({ mutationFn: () => devicesApi.requestScreenshot(deviceId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["screenshots"] }) });
  const remove = useMutation({ mutationFn: devicesApi.deleteScreenshot,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["screenshots"] }) });
  if (!allowed) return <Panel><p className="m-0 p-2 text-[10px] text-[var(--color-muted)]">Screenshot capture requires lab-admin access.</p></Panel>;
  return <div className="grid gap-4">
    <Panel>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={request.isPending} onClick={() => request.mutate()}><Camera size={14} /> {request.isPending ? "Requesting…" : "Capture screen"}</Button>
        <span className="text-[9px] text-[var(--color-muted)]">Requires an online device with an active Windows desktop session.</span>
      </div>
      {request.isError && <p className="mb-0 mt-2 text-[10px] text-red-600">{request.error.message}</p>}
    </Panel>
    {captures.isError && <QueryError error={captures.error} />}
    <Panel>
      <div className="mb-4 flex items-center justify-between"><h2 className="m-0 text-[13px] font-bold">Device captures</h2><span className="text-[9px] text-[var(--color-muted)]">Auto-delete after 24 hours</span></div>
      {captures.isLoading ? <Skeleton rows={3} /> : captures.data?.length ?
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{captures.data.map((capture) => <CaptureCard key={capture.id} capture={capture} deleting={remove.isPending} onDelete={() => remove.mutate(capture.id)} />)}</div>
        : <Empty title="No screenshots captured" detail="Request a screen capture for this device." />}
    </Panel>
  </div>;
}
