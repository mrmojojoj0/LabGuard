import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Loading, PageHeader, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import { devicesApi } from "../devices/api";
import { roomsApi } from "../rooms/api";
import { softwareApi } from "./api";
import type { SoftwareCatalogPackage, WingetDiscoveryResult } from "../../lib/types";

const selectClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";
type DeploymentSelection = { kind: "WINGET"; pkg: WingetDiscoveryResult } | { kind: "CHOCO"; pkg: SoftwareCatalogPackage };

export function SoftwareDeploymentPage() {
  const jobs = useQuery({ queryKey: ["software-jobs"], queryFn: () => softwareApi.jobs(), refetchInterval: 3000 });
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const names = new Map((devices.data ?? []).map((device) => [device.id, device.assigned_name || device.hostname]));
  const { admin } = useAuth();
  const canDeploy = canManageLabs(admin?.role);
  const toast = useToast();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [targetMode, setTargetMode] = useState<"DEVICES" | "LAB">("DEVICES");
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>([]);
  const [roomId, setRoomId] = useState("");
  const [scope, setScope] = useState<"MACHINE" | "USER">("MACHINE");
  const [selection, setSelection] = useState<DeploymentSelection | null>(null);
  const [submittedJobs, setSubmittedJobs] = useState<Array<{ id: string; deviceId: string }>>([]);
  const [batchSummary, setBatchSummary] = useState<string | null>(null);
  const refreshHandled = useRef(new Set<string>());
  const eligibleDevices = (devices.data ?? []).filter((device) => device.enabled && device.enrollment_state === "APPROVED");
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: roomsApi.list });
  const roomLayout = useQuery({ queryKey: ["room-layout", roomId], queryFn: () => roomsApi.layout(roomId), enabled: Boolean(roomId) });
  const labDeviceIds = (roomLayout.data?.assignments ?? []).map((assignment) => assignment.device_id);
  const targetDeviceIds = [...new Set(targetMode === "LAB" ? eligibleDevices.filter((device) => labDeviceIds.includes(device.id)).map((device) => device.id) : selectedDeviceIds.filter((id) => eligibleDevices.some((device) => device.id === id)))];
  const chocolatey = useQuery({
    queryKey: ["software-catalog", "approved-chocolatey"],
    queryFn: () => softwareApi.catalog({ package_manager: "CHOCO", approved: true }),
    enabled: canDeploy,
  });
  const search = useMutation({
    mutationFn: (value: string) => softwareApi.searchWingetRepository(value, "winget"),
    onError: (error: Error) => toast("WinGet search failed. " + error.message, "error"),
  });
  const details = useQuery({
    queryKey: ["winget-package-details", selection?.kind === "WINGET" ? selection.pkg.package_id : null],
    queryFn: () => softwareApi.wingetPackageDetails((selection as Extract<DeploymentSelection, { kind: "WINGET" }>).pkg.package_id),
    enabled: selection?.kind === "WINGET",
    retry: false,
  });
  const createJob = useMutation({
    mutationFn: async () => {
      if (!selection) throw new Error("Select a package before installing.");
      const queued: Array<{ id: string; deviceId: string }> = [];
      const failures: Array<{ deviceId: string; message: string }> = [];
      for (const targetId of targetDeviceIds) {
        try {
          const job = selection.kind === "CHOCO"
            ? await softwareApi.createJob(targetId, { action: "INSTALL", catalog_package_id: selection.pkg.id, installation_scope: "MACHINE" })
            : await softwareApi.createJob(targetId, {
              action: "INSTALL", package_manager: "WINGET", package_id: selection.pkg.package_id,
              source: "winget", installation_scope: scope,
              ...(selection.pkg.version ? { version: selection.pkg.version } : {}),
            });
          queued.push({ id: job.id, deviceId: targetId });
        } catch (error) {
          failures.push({ deviceId: targetId, message: error instanceof Error ? error.message : "Request failed" });
        }
      }
      return { queued, failures };
    },
    onSuccess: ({ queued, failures }) => {
      setSubmittedJobs(queued);
      setSelection(null);
      setBatchSummary(`${queued.length} queued, ${failures.length} failed${failures.length ? ` (${failures.map((failure) => `${names.get(failure.deviceId) ?? failure.deviceId}: ${failure.message}`).join("; ")})` : ""}.`);
      toast(`${queued.length} installation job${queued.length === 1 ? "" : "s"} queued; ${failures.length} failed.`, failures.length ? "error" : "success");
      void qc.invalidateQueries({ queryKey: ["software-jobs"] });
    },
    onError: (error: Error) => toast("Installation was not queued. " + error.message, "error"),
  });
  const submittedJobsReady = submittedJobs.filter(({ id }) => jobs.data?.items.some((job) => job.id === id && job.status === "SUCCEEDED"));
  useEffect(() => {
    for (const job of submittedJobsReady) {
      if (refreshHandled.current.has(job.id)) continue;
      refreshHandled.current.add(job.id);
      void softwareApi.refresh(job.deviceId).then(() => {
        void qc.invalidateQueries({ queryKey: ["device-software", job.deviceId] });
      }).catch((error: Error) => toast(`Installed, but inventory refresh failed. ${error.message}`, "error"));
    }
  }, [submittedJobsReady.map((job) => job.id).join(","), qc, toast]);
  return <>
    <PageHeader eyebrow="SOFTWARE OPERATIONS" title="Software Deployment" description="Search WinGet or choose an approved Chocolatey package, then queue it for selected PCs or an entire lab." />
    <Panel className="mb-4">
      <PanelTitle>Search WinGet and install</PanelTitle>
      {!canDeploy ? <p className="pt-3 text-[10px] text-[var(--color-muted)]">Software installation requires lab-admin access.</p> : <>
        <form className="my-3 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); search.mutate(query.trim()); }}>
          <input className={`${selectClass} min-w-64 flex-1`} aria-label="WinGet search" placeholder="Search package name" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={128} required />
          <Button disabled={!query.trim() || search.isPending}>{search.isPending ? "Searching…" : "Search WinGet"}</Button>
        </form>
        {search.isError && <QueryError error={search.error} />}
        {search.data && <div className="divide-y divide-[var(--color-border)]" aria-live="polite">
          {search.data.results.length === 0 ? <p className="py-3 text-[10px] text-[var(--color-muted)]">No packages matched.</p> : search.data.results.map((result) => <div className="flex flex-wrap items-center justify-between gap-3 py-2" key={`${result.source}:${result.package_id}`}>
            <div><strong className="block text-[10px] text-[var(--color-foreground)]">{result.name}</strong><span className="text-[9px] text-[var(--color-muted)]">{result.package_id} · {result.version || "Latest"} · {result.publisher || "Publisher details loaded on selection"} · {result.source}</span></div>
            <Button onClick={() => { setScope("MACHINE"); setSelection({ kind: "WINGET", pkg: result }); }}>Select package</Button>
          </div>)}
        </div>}
      </>}
    </Panel>
    {canDeploy && <Panel className="mb-4">
      <PanelTitle>Existing Chocolatey packages</PanelTitle>
      <p className="mb-2 text-[9px] text-[var(--color-muted)]">Existing approved Chocolatey packages continue to use the configured feed and machine-scope adapter.</p>
      {chocolatey.isError && <QueryError error={chocolatey.error} />}
      {chocolatey.isLoading ? <Loading label="Loading configured Chocolatey packages…" /> : !chocolatey.data?.length
        ? <p className="text-[10px] text-[var(--color-muted)]">No approved Chocolatey packages are available.</p>
        : <div className="divide-y divide-[var(--color-border)]">{chocolatey.data.map((pkg) => <div className="flex flex-wrap items-center justify-between gap-3 py-2" key={pkg.id}>
          <div><strong className="block text-[10px] text-[var(--color-foreground)]">{pkg.display_name}</strong><span className="text-[9px] text-[var(--color-muted)]">{pkg.package_id} · {pkg.publisher || "Publisher unavailable"} · machine scope</span></div>
          <Button onClick={() => { setScope("MACHINE"); setSelection({ kind: "CHOCO", pkg }); }}>Install Chocolatey package</Button>
        </div>)}</div>}
    </Panel>}
    <Panel>
      <PanelTitle>Deployment jobs <span className="text-[9px] font-normal text-[var(--color-muted)]">{jobs.data?.total ?? 0} recent</span></PanelTitle>
      {batchSummary && <p role="status" className="mt-2 rounded-lg bg-[var(--color-surface-subtle)] p-2 text-[10px] text-[var(--color-foreground)]">Last batch: {batchSummary}</p>}
      {jobs.isError && <QueryError error={jobs.error} />}
      {jobs.isLoading ? <Loading label="Loading deployment jobs…" /> : !jobs.data?.items.length ? <p className="pt-3 text-[10px] text-[var(--color-muted)]">No deployment jobs have been requested.</p> :
        <div className="overflow-x-auto"><table className="mt-3 w-full min-w-[780px] text-left text-[10px]">
          <thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">{["Application", "Device", "Operation", "Status", "Progress", "Started", "Completed", "Result"].map((label) => <th className="px-2 py-2 font-semibold" key={label}>{label}</th>)}</tr></thead>
          <tbody>{jobs.data.items.map((job) => <tr className="border-b border-[var(--color-border)] last:border-0" key={job.id}>
            <td className="px-2 py-3 font-semibold text-[var(--color-foreground)]">{job.package_id}{job.requested_version ? ` ${job.requested_version}` : ""}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{names.get(job.device_id) ?? job.device_id}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.action}</td>
            <td className="px-2 py-3 text-[var(--color-foreground)]">{job.status}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.progress_percent}% {job.progress_message ?? ""}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.completed_at ? new Date(job.completed_at).toLocaleString() : "—"}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.error_message || job.result_summary || job.result_code || "—"}</td>
          </tr>)}</tbody>
        </table></div>}
    </Panel>
    {selection && <div className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/45 p-4" role="presentation">
      <section className="w-full max-w-lg rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby="direct-install-confirm-title">
        <h2 id="direct-install-confirm-title" className="text-lg font-bold text-[var(--color-foreground)]">Confirm {selection.kind === "WINGET" ? "WinGet" : "Chocolatey"} installation</h2>
        {selection.kind === "WINGET" && details.isLoading ? <Loading label="Verifying exact WinGet package…" /> : selection.kind === "WINGET" && details.isError ? <QueryError error={details.error} /> : <>
          <p className="my-3 text-[11px] text-[var(--color-muted)]">{selection.kind === "WINGET" ? details.data?.display_name : selection.pkg.display_name} · {selection.pkg.package_id} · {selection.kind === "WINGET" ? selection.pkg.version || details.data?.version || "latest" : selection.pkg.version_policy} · {selection.kind === "WINGET" ? details.data?.publisher || "Publisher unavailable" : selection.pkg.publisher || "Publisher unavailable"} · {selection.kind === "WINGET" ? details.data?.source : selection.pkg.source}</p>
          <div className="grid gap-3">
            <label className="text-[10px] text-[var(--color-muted)]">Target type <select className={`${selectClass} ml-2`} aria-label="Deployment target type" value={targetMode} onChange={(event) => setTargetMode(event.target.value as "DEVICES" | "LAB")}><option value="DEVICES">Select individual PCs</option><option value="LAB">Entire lab</option></select></label>
            {targetMode === "LAB" ? <div className="grid gap-2">
              <label className="text-[10px] text-[var(--color-muted)]">Lab <select className={`${selectClass} ml-2`} aria-label="Deployment lab" value={roomId} onChange={(event) => setRoomId(event.target.value)}><option value="">Select a lab</option>{(rooms.data ?? []).map((room) => <option value={room.id} key={room.id}>{room.name}</option>)}</select></label>
              {roomLayout.isLoading && roomId && <Loading label="Loading lab devices…" />}
              {roomLayout.isError && <QueryError error={roomLayout.error} />}
              {roomId && roomLayout.data && <p className="text-[10px] text-[var(--color-muted)]">{targetDeviceIds.length} of {labDeviceIds.length} PCs in {roomLayout.data.room.name} are enabled and approved. Eligible devices will receive individual jobs.</p>}
            </div> : <div className="max-h-40 overflow-auto rounded-lg border border-[var(--color-border)] p-2">
              <p className="mb-2 text-[10px] text-[var(--color-muted)]">Select one or more enabled, approved PCs.</p>
              {eligibleDevices.map((device) => <label className="flex items-center gap-2 py-1 text-[10px] text-[var(--color-foreground)]" key={device.id}><input type="checkbox" checked={selectedDeviceIds.includes(device.id)} onChange={(event) => setSelectedDeviceIds((current) => event.target.checked ? [...current, device.id] : current.filter((id) => id !== device.id))} />{device.assigned_name || device.hostname}</label>)}
              {!eligibleDevices.length && <p className="text-[10px] text-[var(--color-muted)]">No enabled, approved devices are available.</p>}
            </div>}
            <p className="text-[10px] text-[var(--color-muted)]">Selected targets: {targetDeviceIds.length}{targetDeviceIds.length ? ` · ${targetDeviceIds.map((targetId) => names.get(targetId) ?? targetId).join(", ")}` : ""}</p>
            {selection.kind === "WINGET" ? <label className="text-[10px] text-[var(--color-muted)]">Installation scope <select className={`${selectClass} ml-2`} aria-label="Installation scope" value={scope} onChange={(event) => setScope(event.target.value as "MACHINE" | "USER")}><option value="MACHINE">Machine</option><option value="USER">Current user (foreground agent only)</option></select></label> : <span className="text-[10px] text-[var(--color-muted)]">Installation scope: machine</span>}
          </div>
        </>}
        {createJob.isError && <div role="alert" className="mt-3 text-[10px] text-red-700">{createJob.error.message}</div>}
        <div className="mt-5 flex justify-end gap-2"><Button disabled={createJob.isPending} onClick={() => setSelection(null)}>Cancel</Button><Button className="bg-[var(--color-primary)] text-white" disabled={(selection.kind === "WINGET" && (details.isLoading || details.isError)) || targetDeviceIds.length === 0 || (targetMode === "LAB" && (roomLayout.isLoading || roomLayout.isError)) || !canDeploy || createJob.isPending} onClick={() => createJob.mutate()}>{createJob.isPending ? "Submitting jobs…" : `Confirm installation for ${targetDeviceIds.length} PC${targetDeviceIds.length === 1 ? "" : "s"}`}</Button></div>
      </section>
    </div>}
  </>;
}
