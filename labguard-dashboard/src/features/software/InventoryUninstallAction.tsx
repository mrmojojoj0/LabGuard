import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import type { SoftwareItem } from "../../lib/types";
import { softwareApi } from "./api";
import { displayJobProgressMessage } from "./jobProgress";

export function canSafelyUninstall(item: SoftwareItem) {
  const manager = item.source === "WINGET" || item.source === "CHOCO";
  return manager && item.package_id !== null
    && /^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/.test(item.package_id)
    && (item.source === "WINGET"
      ? item.installation_scope === "MACHINE" || item.installation_scope === "USER"
      : item.installation_scope === "MACHINE");
}

export function InventoryUninstallAction({ deviceId, item, disabled = false }: { deviceId: string; item: SoftwareItem; disabled?: boolean }) {
  const { admin } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(null);
  const refreshHandled = useRef(false);
  const jobs = useQuery({ queryKey: ["software-jobs", deviceId], queryFn: () => softwareApi.jobs(deviceId), refetchInterval: 3000 });
  const manager = item.source === "WINGET" || item.source === "CHOCO" ? item.source : null;
  const safelyIdentified = useMemo(() => canSafelyUninstall(item), [item]);
  const createJob = useMutation({
    mutationFn: () => softwareApi.createJob(deviceId, { action: "UNINSTALL", inventory_item_id: item.id }),
    onSuccess: (job) => {
      refreshHandled.current = false;
      setConfirm(false);
      setSubmittedJobId(job.id);
      toast("Uninstallation queued.");
      void qc.invalidateQueries({ queryKey: ["software-jobs", deviceId] });
      void qc.invalidateQueries({ queryKey: ["software-jobs"] });
    },
    onError: (error: Error) => toast("Uninstallation was not queued. " + error.message, "error"),
  });
  const submittedJob = jobs.data?.items.find((job) => job.id === submittedJobId);
  useEffect(() => {
    if (submittedJob?.status === "SUCCEEDED" && !refreshHandled.current) {
      refreshHandled.current = true;
      void qc.invalidateQueries({ queryKey: ["device-software", deviceId] });
      toast("Uninstallation verified; installed software inventory refreshed.");
    }
  }, [submittedJob?.status, deviceId, item.id, qc, toast]);

  if (!safelyIdentified) return <span className="text-[9px] text-[var(--color-muted)]" title="Requires an exact supported package ID and scope">Unavailable: no exact supported package identity</span>;
  if (!canManageLabs(admin?.role)) return <span className="text-[9px] text-[var(--color-muted)]">Uninstall requires lab-admin access</span>;
  return <div className="flex flex-wrap items-center justify-end gap-2">
    {submittedJob && <span role="status" className="text-[9px] text-[var(--color-muted)]">{submittedJob.status}{submittedJob.status === "FAILED"
      ? `: ${submittedJob.error_message || submittedJob.result_code || "Operation failed without details."}${submittedJob.result_summary && submittedJob.result_summary !== submittedJob.error_message ? ` · ${submittedJob.result_summary}` : ""}`
      : `: ${submittedJob.progress_percent}% ${displayJobProgressMessage(submittedJob.status, submittedJob.progress_message) || submittedJob.result_summary || ""}`}</span>}
    {jobs.isError && <span role="alert" className="text-[9px] text-red-700">Job status unavailable.</span>}
    <Button className="border-red-200 text-red-700" disabled={disabled || createJob.isPending || Boolean(submittedJob && !["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(submittedJob.status))} onClick={() => setConfirm(true)}>Uninstall</Button>
    {confirm && <div className="fixed inset-0 z-[110] grid place-items-center bg-slate-950/45 p-4" role="presentation">
      <section className="w-full max-w-md rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby={`uninstall-title-${item.id}`}>
        <h2 id={`uninstall-title-${item.id}`} className="text-lg font-bold text-[var(--color-foreground)]">Confirm uninstallation</h2>
        <p className="my-3 text-[11px] text-[var(--color-muted)]">Remove <strong>{item.name}</strong> using exact {manager} package <strong>{item.package_id}</strong> ({item.installation_scope}) from this device? The official package manager will be used; LabGuard will not run registry uninstall strings.</p>
        {createJob.isError && <div role="alert" className="mb-3 text-[10px] text-red-700">{createJob.error.message}</div>}
        <div className="flex justify-end gap-2"><Button disabled={createJob.isPending} onClick={() => setConfirm(false)}>Cancel</Button><Button className="border-red-200 text-red-700" disabled={createJob.isPending} onClick={() => createJob.mutate()}>{createJob.isPending ? "Submitting…" : "Confirm uninstallation"}</Button></div>
      </section>
    </div>}
  </div>;
}
