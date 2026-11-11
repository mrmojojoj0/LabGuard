import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { softwareApi } from "./api";
import { devicesApi } from "../devices/api";
import type { SoftwareAggregate, SoftwareItem } from "../../lib/types";
import { Empty, Loading, PageHeader, Panel, PanelTitle, QueryError, Button } from "../../components/ui";
import { canSafelyUninstall } from "./InventoryUninstallAction";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import { useToast } from "../../components/Toast";

const TERMINAL_JOB_STATES = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"]);
const ACTIVE_JOB_STATES = new Set(["PENDING", "DISPATCHED", "RUNNING"]);
const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const selectClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";

export function SoftwarePage() {
  const qc = useQueryClient();
  const { admin } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [publisher, setPublisher] = useState("");
  const [source, setSource] = useState("");
  const [scope, setScope] = useState("");
  const [version, setVersion] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Pick<SoftwareAggregate, "software_key" | "name" | "publisher"> | null>(null);
  const [selectedInstallations, setSelectedInstallations] = useState<Set<string>>(new Set());
  const [confirmBulkUninstall, setConfirmBulkUninstall] = useState(false);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ index: number; total: number; name: string } | null>(null);
  const summary = useQuery({ queryKey: ["software-summary"], queryFn: softwareApi.summary });
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const result = useQuery({
    queryKey: ["software", search, publisher, source, scope, version, deviceId, page],
    queryFn: () => softwareApi.list({ search, publisher, source, installation_scope: scope, version, device_id: deviceId, offset: page * 50, limit: 50 }),
  });
  const installations = useQuery({
    queryKey: ["software-installations", selected?.software_key],
    queryFn: () => softwareApi.installations(selected!.software_key),
    enabled: Boolean(selected),
  });
  const resetPage = (setter: (value: string) => void) => (value: string) => { setter(value); setPage(0); };
  const installationItems = installations.data?.items ?? [];
  const supportedInstallations = installationItems.filter(canSafelyUninstall);
  const chosenInstallations = installationItems.filter((item) => selectedInstallations.has(item.id) && canSafelyUninstall(item));
  const allInstallationsSelected = supportedInstallations.length > 0 && supportedInstallations.every((item) => selectedInstallations.has(item.id));
  const toggleInstallations = () => setSelectedInstallations(allInstallationsSelected
    ? new Set()
    : new Set(supportedInstallations.map((item) => item.id)));
  const toggleInstallation = (item: SoftwareItem) => setSelectedInstallations((current) => {
    const next = new Set(current);
    if (next.has(item.id)) next.delete(item.id);
    else if (canSafelyUninstall(item)) next.add(item.id);
    return next;
  });
  const runBulkUninstall = async () => {
    if (!chosenInstallations.length || bulkRunning) return;
    setBulkRunning(true);
    setConfirmBulkUninstall(false);
    const failures: string[] = [];
    let completed = 0;
    let stoppedEarly = false;
    try {
      for (const [index, item] of chosenInstallations.entries()) {
        const deviceName = item.device_name || item.hostname || item.device_id;
        setBulkProgress({ index: index + 1, total: chosenInstallations.length, name: `${item.name} · ${deviceName}` });
        try {
          const queueDeadline = Date.now() + 30 * 60 * 1000;
          while (true) {
            const page = await softwareApi.jobs(item.device_id);
            if (!page.items.some((job) => ACTIVE_JOB_STATES.has(job.status))) break;
            if (Date.now() >= queueDeadline) throw new Error(`A software job is still active on ${deviceName}; bulk uninstall stopped.`);
            await delay(2000);
          }
          const created = await softwareApi.createJob(item.device_id, { action: "UNINSTALL", inventory_item_id: item.id });
          const deadline = Math.min(new Date(created.expires_at).getTime() + 60_000, Date.now() + 31 * 60 * 1000);
          let finishedJob: Awaited<ReturnType<typeof softwareApi.jobs>>["items"][number] | undefined;
          while (Date.now() < deadline) {
            const page = await softwareApi.jobs(item.device_id);
            finishedJob = page.items.find((job) => job.id === created.id);
            if (finishedJob && TERMINAL_JOB_STATES.has(finishedJob.status)) break;
            await delay(2000);
          }
          if (!finishedJob || !TERMINAL_JOB_STATES.has(finishedJob.status)) {
            failures.push(`${item.name} (${deviceName}): timed out waiting for agent`);
            stoppedEarly = true;
            break;
          }
          if (finishedJob.status === "SUCCEEDED") completed += 1;
          else failures.push(`${item.name} (${deviceName}): ${finishedJob.error_message || finishedJob.result_code || finishedJob.status}${finishedJob.result_summary && finishedJob.result_summary !== finishedJob.error_message ? ` · ${finishedJob.result_summary}` : ""}`);
        } catch (error) {
          const message = error instanceof Error ? error.message : "request failed";
          failures.push(`${item.name} (${deviceName}): ${message}`);
          if (message.includes("still active")) { stoppedEarly = true; break; }
        }
      }
    } finally {
      setBulkRunning(false);
      setBulkProgress(null);
      setSelectedInstallations(new Set());
      void qc.invalidateQueries({ queryKey: ["software-installations", selected?.software_key] });
      void qc.invalidateQueries({ queryKey: ["software"] });
      void qc.invalidateQueries({ queryKey: ["software-jobs"] });
      for (const item of chosenInstallations) void qc.invalidateQueries({ queryKey: ["software-jobs", item.device_id] });
      if (failures.length) toast(`Bulk uninstall finished: ${completed}/${chosenInstallations.length} removed. ${stoppedEarly ? "Stopped because a job did not finish." : `${failures.length} failed.`} ${failures.slice(0, 3).join("; ")}`, "error");
      else toast(`Bulk uninstall finished: ${completed}/${chosenInstallations.length} removed.`);
    }
  };
  return <>
    <PageHeader eyebrow="MONITORING" title="Software Inventory" description="Read-only inventory reported by enrolled Windows devices." />
    {summary.isError && <QueryError error={summary.error} />}
    <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {[
        ["Unique applications", summary.data?.unique_applications],
        ["Installations", summary.data?.total_installations],
        ["Devices reporting", summary.data?.devices_with_successful_inventory],
        ["Stale inventories", summary.data?.stale_devices],
        ["Never reported", summary.data?.never_reported_devices],
      ].map(([label, value]) => <Panel key={label}><p className="text-[9px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">{label}</p><strong className="mt-2 block text-2xl text-[var(--color-foreground)]">{value ?? "â€”"}</strong></Panel>)}
    </div>
    <Panel className="mb-4">
      <PanelTitle>Most commonly installed <span className="text-[9px] font-normal text-[var(--color-muted)]">· {summary.data?.collecting_devices ?? 0} collecting · {summary.data?.partial_devices ?? 0} partial</span></PanelTitle>
      <div className="mt-3 flex flex-wrap gap-2">{summary.data?.most_common.map((item) => <button key={item.software_key} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-2 text-left" onClick={() => { setSelectedInstallations(new Set()); setSelected(item); }}><strong className="block text-[10px] text-[var(--color-foreground)]">{item.name}</strong><span className="text-[9px] text-[var(--color-muted)]">{item.installation_count} installations on {item.device_count} devices</span></button>)}</div>
    </Panel>
    <Panel>
      <PanelTitle>Installed applications <span className="text-[9px] font-normal text-[var(--color-muted)]">{result.data?.total ?? 0} matching applications</span></PanelTitle>
      <div className="my-4 flex flex-wrap gap-2">
        <label className="flex h-9 min-w-52 flex-1 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5"><Search size={14} className="text-[var(--color-muted)]"/><input className="w-full bg-transparent text-[10px] text-[var(--color-foreground)] outline-none" placeholder="Search app or publisher" value={search} onChange={(e) => resetPage(setSearch)(e.target.value)} /></label>
        <input className={selectClass} placeholder="Publisher" aria-label="Filter publisher" value={publisher} onChange={(e) => resetPage(setPublisher)(e.target.value)} />
        <input className={selectClass} placeholder="Version" aria-label="Filter version" value={version} onChange={(e) => resetPage(setVersion)(e.target.value)} />
        <select className={selectClass} aria-label="Filter source" value={source} onChange={(e) => resetPage(setSource)(e.target.value)}><option value="">All sources</option><option value="WINDOWS_REGISTRY">Windows registry</option><option value="WINGET">winget</option><option value="CHOCO">Chocolatey</option></select>
        <select className={selectClass} aria-label="Filter scope" value={scope} onChange={(e) => resetPage(setScope)(e.target.value)}><option value="">All scopes</option><option value="MACHINE">Machine</option><option value="USER">User</option><option value="UNKNOWN">Unknown</option></select>
        <select className={selectClass} aria-label="Filter device" value={deviceId} onChange={(e) => resetPage(setDeviceId)(e.target.value)}><option value="">All devices</option>{devices.data?.map((device) => <option value={device.id} key={device.id}>{device.assigned_name || device.hostname}</option>)}</select>
      </div>
      {result.isError && <QueryError error={result.error} />}
      {result.isLoading ? <Loading label="Loading software inventoryâ€¦" /> : !result.data?.items.length ? <Empty title="No software inventory found" detail="Try changing the filters or wait for an enrolled device to report inventory." /> : <>
        <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-[10px]"><thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">{["Application", "Publisher", "Installations", "Source"].map((label) => <th className="px-2 py-2 font-semibold" key={label}>{label}</th>)}</tr></thead><tbody>{result.data.items.map((item) => <tr className="border-b border-[var(--color-border)] last:border-0" key={item.software_key}><td className="px-2 py-3"><button className="text-left font-semibold text-[var(--color-primary)] hover:underline" onClick={() => { setSelectedInstallations(new Set()); setSelected(item); }}>{item.name}</button></td><td className="px-2 py-3 text-[var(--color-muted)]">{item.publisher ?? "â€”"}</td><td className="px-2 py-3 text-[var(--color-foreground)]">{item.installation_count} on {item.device_count} devices</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.source}</td></tr>)}</tbody></table></div>
        <div className="mt-3 flex items-center justify-between text-[10px] text-[var(--color-muted)]"><span>Page {page + 1} of {Math.max(1, Math.ceil(result.data.total / 50))}</span><div className="flex gap-2"><button className={selectClass} disabled={!page} onClick={() => setPage(page - 1)}>Previous</button><button className={selectClass} disabled={(page + 1) * 50 >= result.data.total} onClick={() => setPage(page + 1)}>Next</button></div></div>
      </>}
    </Panel>
    {selected && <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/35" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelected(null); }}><aside className="h-full w-full max-w-xl overflow-y-auto border-l border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" aria-label={`${selected.name} installations`}><div className="flex items-start justify-between"><div><p className="text-[9px] font-bold uppercase tracking-wider text-[var(--color-muted)]">APPLICATION</p><h2 className="my-1 text-xl font-bold text-[var(--color-foreground)]">{selected.name}</h2><p className="text-[10px] text-[var(--color-muted)]">{selected.publisher ?? "Publisher unavailable"}</p></div><button className="rounded p-2 text-[var(--color-muted)]" aria-label="Close installations" onClick={() => { setSelected(null); setSelectedInstallations(new Set()); }}><X size={18}/></button></div><div className="mt-6 flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-2"><h3 className="text-xs font-bold text-[var(--color-foreground)]">Installed on</h3>{canManageLabs(admin?.role) && <div className="flex gap-2"><Button disabled={!supportedInstallations.length || bulkRunning} onClick={toggleInstallations}>{allInstallationsSelected ? "Clear selection" : "Select supported"}</Button><Button className="border-red-200 text-red-700" disabled={!chosenInstallations.length || bulkRunning} onClick={() => setConfirmBulkUninstall(true)}>Uninstall selected ({chosenInstallations.length})</Button></div>}</div>{bulkProgress && <p className="my-3 rounded bg-amber-50 p-2 text-[10px] text-amber-900" role="status">Uninstalling {bulkProgress.index} of {bulkProgress.total}: {bulkProgress.name}. Please keep this panel open.</p>}{installations.isError && <QueryError error={installations.error}/ >}{installations.isLoading ? <Loading label="Loading device installations…"/> : <div className="divide-y divide-[var(--color-border)]">{installationItems.map((item) => <div className="flex items-center gap-3 py-3" key={item.id}>{canManageLabs(admin?.role) && <input aria-label={`Select ${item.name} on ${item.device_name || item.hostname || item.device_id}`} type="checkbox" disabled={!canSafelyUninstall(item) || bulkRunning} checked={selectedInstallations.has(item.id)} onChange={() => toggleInstallation(item)}/>}<div className="min-w-0"><strong className="block text-[11px] text-[var(--color-foreground)]">{item.device_name || item.hostname || item.device_id}</strong><span className="text-[9px] text-[var(--color-muted)]">{item.version || "Version unavailable"} · {item.source} · {item.installation_scope.toLowerCase()}</span>{!canSafelyUninstall(item) && <span className="ml-2 text-[9px] text-[var(--color-muted)]">Uninstall unavailable</span>}</div></div>)}</div>}</aside></div>}
    {confirmBulkUninstall && <div className="fixed inset-0 z-[120] grid place-items-center bg-slate-950/45 p-4" role="presentation"><section className="max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby="aggregate-bulk-uninstall-title"><h2 id="aggregate-bulk-uninstall-title" className="text-lg font-bold text-[var(--color-foreground)]">Confirm bulk uninstall</h2><p className="my-3 text-[11px] text-[var(--color-muted)]">The selected installations of {selected.name} will be uninstalled from their listed devices, one job at a time.</p><ul className="max-h-56 overflow-y-auto rounded-lg border border-[var(--color-border)] p-3 text-[10px]">{chosenInstallations.map((item) => <li key={item.id} className="py-1">{item.device_name || item.hostname || item.device_id} <span className="text-[var(--color-muted)]">· {item.version || "Version unavailable"} · {item.installation_scope}</span></li>)}</ul><p className="my-3 text-[10px] text-amber-700">Uninstalling software may remove data or disrupt a device. Review the selected devices before continuing.</p><div className="flex justify-end gap-2"><Button onClick={() => setConfirmBulkUninstall(false)}>Cancel</Button><Button className="border-red-200 text-red-700" onClick={() => void runBulkUninstall()}>Confirm and uninstall</Button></div></section></div>}
  </>;
}
