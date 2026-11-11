import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckSquare, RefreshCw, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Empty, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import type { SoftwareItem } from "../../lib/types";
import { softwareApi } from "./api";
import { canSafelyUninstall, InventoryUninstallAction } from "./InventoryUninstallAction";
import { DeviceSoftwareInstaller } from "./DeviceSoftwareInstaller";

const TERMINAL_JOB_STATES = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"]);
const ACTIVE_JOB_STATES = new Set(["PENDING", "DISPATCHED", "RUNNING"]);
const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function DeviceSoftware({ id }: { id: string }) {
  const qc = useQueryClient();
  const { admin } = useAuth();
  const toast = useToast();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkConfirm, setShowBulkConfirm] = useState(false);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ index: number; total: number; name: string } | null>(null);
  const [page, setPage] = useState(0);
  const [refreshRequestedAt, setRefreshRequestedAt] = useState<number | null>(null);
  const pageSize = 100;
  const queryKey = ["device-software", id, page];
  const result = useQuery({
    queryKey,
    queryFn: () => softwareApi.device(id, { offset: page * pageSize, limit: pageSize }),
    refetchInterval: (query) => {
      const collecting = query.state.data?.collection.status === "IN_PROGRESS";
      const awaitingRefresh = refreshRequestedAt !== null && Date.now() - refreshRequestedAt < 2 * 60 * 1000;
      return collecting || awaitingRefresh ? 3000 : false;
    },
  });
  const refresh = useMutation({
    mutationFn: () => softwareApi.refresh(id),
    onSuccess: () => {
      setRefreshRequestedAt(Date.now());
      toast("Inventory refresh requested.");
      void qc.invalidateQueries({ queryKey });
    },
    onError: (error: Error) => toast(`Inventory refresh failed. ${error.message}`, "error"),
  });
  const collection = result.data?.collection;
  const successfulAt = collection?.last_successful_at;
  const stale = collection?.stale;
  const items = result.data?.items ?? [];
  const total = result.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const firstItem = total ? page * pageSize + 1 : 0;
  const lastItem = Math.min((page + 1) * pageSize, total);
  useEffect(() => {
    if (result.data && page >= pageCount) {
      setSelectedIds(new Set());
      setPage(pageCount - 1);
    }
  }, [result.data, page, pageCount]);
  const supportedItems = items.filter(canSafelyUninstall);
  const visibleItems = supportedItems;
  const selectedItems = visibleItems.filter((item) => selectedIds.has(item.id));
  const allSupportedSelected = supportedItems.length > 0 && supportedItems.every((item) => selectedIds.has(item.id));

  const toggleSelected = (item: SoftwareItem) => setSelectedIds((current) => {
    const next = new Set(current);
    if (next.has(item.id)) next.delete(item.id);
    else if (canSafelyUninstall(item)) next.add(item.id);
    return next;
  });
  const toggleAllSupported = () => setSelectedIds(allSupportedSelected
    ? new Set()
    : new Set(supportedItems.map((item) => item.id)));

  const changePage = (nextPage: number) => {
    setSelectedIds(new Set());
    setPage(Math.max(0, Math.min(nextPage, pageCount - 1)));
  };

  const runBulkUninstall = async () => {
    if (!selectedItems.length || bulkRunning) return;
    setBulkRunning(true);
    setShowBulkConfirm(false);
    const failures: string[] = [];
    let completed = 0;
    let stoppedEarly = false;
    try {
      for (const [index, item] of selectedItems.entries()) {
        setBulkProgress({ index: index + 1, total: selectedItems.length, name: item.name });
        try {
          // Only one software job can be active for a device at a time.
          const queueDeadline = Date.now() + 30 * 60 * 1000;
          while (true) {
            const page = await softwareApi.jobs(id);
            if (!page.items.some((job) => ACTIVE_JOB_STATES.has(job.status))) break;
            if (Date.now() >= queueDeadline) throw new Error("Another software job is still active; bulk uninstall stopped.");
            await delay(2000);
          }
          const created = await softwareApi.createJob(id, { action: "UNINSTALL", inventory_item_id: item.id });
          const jobDeadline = Math.min(new Date(created.expires_at).getTime() + 60_000, Date.now() + 31 * 60 * 1000);
          let finishedJob: Awaited<ReturnType<typeof softwareApi.jobs>>["items"][number] | undefined;
          while (Date.now() < jobDeadline) {
            const page = await softwareApi.jobs(id);
            finishedJob = page.items.find((job) => job.id === created.id);
            if (finishedJob && TERMINAL_JOB_STATES.has(finishedJob.status)) break;
            await delay(2000);
          }
          if (!finishedJob || !TERMINAL_JOB_STATES.has(finishedJob.status)) {
            failures.push(`${item.name}: timed out waiting for agent result`);
            stoppedEarly = true;
            break;
          }
          if (finishedJob.status !== "SUCCEEDED") failures.push(`${item.name}: ${finishedJob.error_message || finishedJob.result_code || finishedJob.status}${finishedJob.result_summary && finishedJob.result_summary !== finishedJob.error_message ? ` · ${finishedJob.result_summary}` : ""}`);
          else completed += 1;
        } catch (error) {
          const message = error instanceof Error ? error.message : "request failed";
          failures.push(`${item.name}: ${message}`);
          if (message.includes("still active")) { stoppedEarly = true; break; }
        }
      }
    } finally {
      setBulkRunning(false);
      setBulkProgress(null);
      setSelectedIds(new Set());
      void qc.invalidateQueries({ queryKey: ["device-software", id] });
      void qc.invalidateQueries({ queryKey: ["software-jobs", id] });
      void qc.invalidateQueries({ queryKey: ["software-jobs"] });
      if (failures.length) toast(`Bulk uninstall finished: ${completed}/${selectedItems.length} removed. ${stoppedEarly ? "Stopped because a job did not finish." : `${failures.length} failed.`} ${failures.slice(0, 3).join("; ")}`, "error");
      else toast(`Bulk uninstall finished: ${completed}/${selectedItems.length} removed.`);
    }
  };

  return <>
    {canManageLabs(admin?.role) && <DeviceSoftwareInstaller deviceId={id} />}
    <Panel>
      <PanelTitle aside={canManageLabs(admin?.role) ? <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!supportedItems.length || bulkRunning} onClick={toggleAllSupported}>{allSupportedSelected ? <CheckSquare size={13}/> : <Square size={13}/>}Select supported</Button>
        <Button className="border-red-200 text-red-700" disabled={!selectedItems.length || bulkRunning} onClick={() => setShowBulkConfirm(true)}>Uninstall selected ({selectedItems.length})</Button>
        <Button disabled={refresh.isPending || bulkRunning} onClick={() => refresh.mutate()}><RefreshCw size={13} className={refresh.isPending ? "animate-spin" : ""}/>{refresh.isPending ? "Requesting…" : "Refresh inventory"}</Button>
      </div> : undefined}>Installed software</PanelTitle>
      {bulkProgress && <div className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-[10px] text-amber-900" role="status">Uninstalling {bulkProgress.index} of {bulkProgress.total}: <strong>{bulkProgress.name}</strong>. Keep this page open while the agent processes each package.</div>}
      <div className="my-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg bg-[var(--color-surface-subtle)] p-3 text-[10px]">
        <span><b className="text-[var(--color-foreground)]">Collection:</b> <span className="text-[var(--color-muted)]">{collection?.status ?? "Loading"}</span></span>
        <span><b className="text-[var(--color-foreground)]">Last attempt:</b> <span className="text-[var(--color-muted)]">{collection?.last_attempt_at ? new Date(collection.last_attempt_at).toLocaleString() : "Never"}</span></span>
        <span><b className="text-[var(--color-foreground)]">Last successful:</b> <span className="text-[var(--color-muted)]">{successfulAt ? new Date(successfulAt).toLocaleString() : "Never"}</span></span>
        <span><b className="text-[var(--color-foreground)]">Last complete:</b> <span className="text-[var(--color-muted)]">{collection?.last_complete_at ? new Date(collection.last_complete_at).toLocaleString() : "Never"}</span></span>
        <span className={`font-semibold ${stale ? "text-amber-600" : "text-emerald-600"}`}>{stale ? "Stale inventory" : collection?.status === "NEVER" ? "No inventory yet" : collection?.status === "FAILED" ? "Latest attempt failed; showing last successful snapshot" : collection?.status === "PARTIAL" ? "Current partial inventory" : "Current"}</span>
        {Boolean(collection?.errors.length) && <span className="text-amber-700">Partial collection: {collection?.errors.join(", ")}</span>}
      </div>
      {result.isError && <QueryError error={result.error}/>}
      {!result.isLoading && total > 0 && <div className="mb-2 flex items-center justify-between text-[10px] text-[var(--color-muted)]"><span>{visibleItems.length} supported entries shown on page {page + 1} of {pageCount} · {total} inventory entries</span>{pageCount > 1 && <div className="flex items-center gap-2"><Button disabled={page === 0} onClick={() => changePage(page - 1)}>Previous</Button><span>Page {page + 1} of {pageCount}</span><Button disabled={page + 1 >= pageCount} onClick={() => changePage(page + 1)}>Next</Button></div>}</div>}
      {result.isLoading ? <Loading label="Loading device software…"/> : !visibleItems.length ? <Empty title={total ? "No supported applications on this page" : "No installed software reported"} detail={total ? "Applications without an exact supported package identity are hidden. Use the page controls to see other entries." : "The agent reports inventory after authentication and on its configured schedule."}/> : <div className="overflow-x-auto"><table className="w-full min-w-[920px] text-left text-[10px]"><thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]"><th className="w-9 px-2 py-2"><input aria-label="Select all supported software" type="checkbox" disabled={!supportedItems.length || bulkRunning} checked={allSupportedSelected} onChange={toggleAllSupported}/></th>{["Application", "Version", "Publisher", "Architecture", "Installed", "Scope / sources", "Action"].map((item) => <th className="px-2 py-2 font-semibold" key={item}>{item}</th>)}</tr></thead><tbody>{visibleItems.map((item) => <tr className="border-b border-[var(--color-border)] last:border-0" key={item.id}><td className="px-2 py-3"><input aria-label={`Select ${item.name} for uninstall`} type="checkbox" disabled={bulkRunning || !canManageLabs(admin?.role)} checked={selectedIds.has(item.id)} onChange={() => toggleSelected(item)}/></td><td className="px-2 py-3 font-semibold text-[var(--color-foreground)]">{item.name}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.version || "—"}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.publisher || "—"}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.architecture}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.install_date || "—"}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.installation_scope} · {(item.discovery_sources ?? [item.source]).join(" + ")}</td><td className="px-2 py-3"><InventoryUninstallAction deviceId={id} item={item} disabled={bulkRunning}/></td></tr>)}</tbody></table></div>}
      {collection?.status === "IN_PROGRESS" && <p className="mt-3 text-[9px] text-[var(--color-muted)]">A scan is still running. The list updates when the collection completes.</p>}
    </Panel>
    {showBulkConfirm && <div className="fixed inset-0 z-[120] grid place-items-center bg-slate-950/45 p-4" role="presentation"><section className="max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby="bulk-uninstall-title"><h2 id="bulk-uninstall-title" className="text-lg font-bold text-[var(--color-foreground)]">Confirm bulk uninstall</h2><p className="my-3 text-[11px] text-[var(--color-muted)]">LabGuard will uninstall these {selectedItems.length} applications from this device, one at a time, using their supported package managers.</p><ul className="max-h-56 overflow-y-auto rounded-lg border border-[var(--color-border)] p-3 text-[10px]">{selectedItems.map((item) => <li key={item.id} className="py-1">{item.name} <span className="text-[var(--color-muted)]">({item.source} · {item.package_id} · {item.installation_scope})</span></li>)}</ul><p className="my-3 text-[10px] text-amber-700">Uninstalling software can remove data or disrupt this device. Review the list before continuing.</p><div className="flex justify-end gap-2"><Button onClick={() => setShowBulkConfirm(false)}>Cancel</Button><Button className="border-red-200 text-red-700" onClick={() => void runBulkUninstall()}>Confirm and uninstall</Button></div></section></div>}
  </>;
}
