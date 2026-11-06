import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Empty, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import type { SoftwareCatalogPackage, SoftwareItem } from "../../lib/types";
import { softwareApi } from "./api";

type Selection =
  | { action: "INSTALL"; pkg: SoftwareCatalogPackage }
  | { action: "UNINSTALL"; pkg: SoftwareCatalogPackage; item: SoftwareItem };
const selectClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";

export function SoftwareManagementControls({ id, items }: { id: string; items: SoftwareItem[] }) {
  const { admin } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [manager, setManager] = useState<"ALL" | "WINGET" | "CHOCO">("ALL");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [scope, setScope] = useState<"MACHINE" | "USER">("MACHINE");
  const [version, setVersion] = useState("");
  const catalog = useQuery({ queryKey: ["software-catalog", search, manager], queryFn: () => softwareApi.catalog({ search, approved: true, ...(manager === "ALL" ? {} : { package_manager: manager }) }) });
  const jobs = useQuery({ queryKey: ["software-jobs", id], queryFn: () => softwareApi.jobs(id), refetchInterval: 3000 });
  const createJob = useMutation({
    mutationFn: (body: Parameters<typeof softwareApi.createJob>[1]) => softwareApi.createJob(id, body),
    onSuccess: () => {
      toast("Software job queued. It will be delivered when the device is connected.");
      setSelection(null);
      setVersion("");
      void qc.invalidateQueries({ queryKey: ["software-jobs", id] });
      void qc.invalidateQueries({ queryKey: ["software-jobs"] });
    },
    onError: (error: Error) => toast("Software job was not queued. " + error.message, "error"),
  });
  const approved = catalog.data ?? [];
  const uninstallable = useMemo(() => items.flatMap((item) => {
    const manager = item.source === "WINGET" ? "WINGET" : item.source === "CHOCO" ? "CHOCO" : null;
    const pkg = manager && item.package_id ? approved.find((candidate) =>
      candidate.package_manager === manager && candidate.package_id.toLowerCase() === item.package_id!.toLowerCase()
      && candidate.supported_scopes.includes(item.installation_scope as "MACHINE" | "USER")) : undefined;
    return pkg ? [{ item, pkg }] : [];
  }), [items, approved]);
  const canManage = canManageLabs(admin?.role);
  const submit = () => {
    if (!selection) return;
    const body = selection.action === "INSTALL" ? {
      action: "INSTALL" as const, catalog_package_id: selection.pkg.id,
      installation_scope: scope,
      ...(selection.pkg.version_policy === "SELECTABLE" ? { version } : {}),
    } : {
      action: "UNINSTALL" as const, catalog_package_id: selection.pkg.id,
      inventory_item_id: selection.item.id,
      installation_scope: selection.item.installation_scope as "MACHINE" | "USER",
    };
    createJob.mutate(body);
  };
  return <>
    <Panel className="mt-4">
      <PanelTitle>Approved software catalog</PanelTitle>
      <label className="my-3 flex items-center gap-2 rounded-lg border border-[var(--color-border)] px-2.5">
        <Search size={14} className="text-[var(--color-muted)]" />
        <input className="h-9 w-full bg-transparent text-[10px] text-[var(--color-foreground)] outline-none" placeholder="Search approved packages" value={search} onChange={(event) => setSearch(event.target.value)} />
      </label>
      <select className={selectClass} aria-label="Filter package manager" value={manager} onChange={(event) => setManager(event.target.value as typeof manager)}><option value="ALL">All package managers</option><option value="WINGET">WinGet</option><option value="CHOCO">Chocolatey</option></select>
      {catalog.isError && <QueryError error={catalog.error} />}
      {catalog.isLoading ? <Loading label="Loading approved catalog…" /> : !approved.length ?
        <div className="flex min-h-[210px] flex-col items-center justify-center gap-2 text-center"><strong className="text-xs text-[var(--color-foreground)]">No approved packages found</strong><span className="max-w-lg text-[10px] text-[var(--color-muted)]">WinGet and configured Chocolatey packages appear here after a Super Admin reviews and approves them.</span>{admin?.role === "SUPER_ADMIN" && <Link className="text-[10px] font-semibold text-[var(--color-primary)] underline" to="/deployment">Review software catalog</Link>}</div> :
        <div className="divide-y divide-[var(--color-border)]">{approved.map((pkg) => <div className="flex flex-wrap items-center justify-between gap-3 py-3" key={pkg.id}>
          <div><strong className="block text-[11px] text-[var(--color-foreground)]">{pkg.display_name}</strong>
            <span className="text-[9px] text-[var(--color-muted)]">{pkg.package_id} · {pkg.package_manager} · {pkg.version_policy === "PINNED" ? pkg.approved_version : pkg.version_policy.toLowerCase()}</span>
            <span className="block text-[9px] text-[var(--color-muted)]">{pkg.publisher || "Publisher unavailable"} · {pkg.source}</span></div>
          {canManage && <Button onClick={() => { setScope(pkg.supported_scopes[0] ?? "MACHINE"); setSelection({ action: "INSTALL", pkg }); }}>Install</Button>}
        </div>)}</div>}
    </Panel>
    <Panel className="mt-4">
      <PanelTitle>Package-manager uninstallation</PanelTitle>
      {!items.length ? <p className="mt-3 text-[10px] text-[var(--color-muted)]">No installed software is available to review.</p> :
        !uninstallable.length ? <Empty title="No supported uninstall targets" detail="Only present WinGet or Chocolatey entries matching an approved package can be removed. Other registry applications are unsupported." /> :
        <div className="divide-y divide-[var(--color-border)]">{uninstallable.map(({ item, pkg }) => <div className="flex flex-wrap items-center justify-between gap-3 py-3" key={item.id}>
          <div><strong className="block text-[11px] text-[var(--color-foreground)]">{item.name}</strong><span className="text-[9px] text-[var(--color-muted)]">{item.package_id} · {item.version || "version unknown"} · {item.installation_scope}</span></div>
          {canManage && <Button className="border-red-200 text-red-700" onClick={() => setSelection({ action: "UNINSTALL", pkg, item })}>Uninstall</Button>}
        </div>)}</div>}
      {uninstallable.length > 0 && items.length > uninstallable.length && <p className="mt-3 text-[9px] text-[var(--color-muted)]">{items.length - uninstallable.length} other installed entr{items.length - uninstallable.length === 1 ? "y is" : "ies are"} unsupported for managed uninstall because it lacks an exact approved package-manager match.</p>}
    </Panel>
    <Panel className="mt-4">
      <PanelTitle>Software jobs <span className="text-[9px] font-normal text-[var(--color-muted)]">{jobs.data?.total ?? 0}</span></PanelTitle>
      {jobs.isError && <QueryError error={jobs.error} />}
      {jobs.isLoading ? <Loading label="Loading software jobs…" /> : !jobs.data?.items.length ?
        <p className="pt-3 text-[10px] text-[var(--color-muted)]">No software jobs for this device.</p> :
        <div className="overflow-x-auto"><table className="mt-3 w-full min-w-[620px] text-left text-[10px]">
          <thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">{["Application", "Action", "Status", "Progress", "Started", "Result"].map((field) => <th className="px-2 py-2" key={field}>{field}</th>)}</tr></thead>
          <tbody>{jobs.data.items.map((job) => <tr className="border-b border-[var(--color-border)] last:border-0" key={job.id}>
            <td className="px-2 py-3 font-semibold text-[var(--color-foreground)]">{approved.find((pkg) => pkg.id === job.catalog_package_id)?.display_name ?? job.package_id}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.action}</td><td className="px-2 py-3 text-[var(--color-foreground)]">{job.status}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.progress_percent}% {job.progress_message || ""}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</td>
            <td className="px-2 py-3 text-[var(--color-muted)]">{job.error_message || job.result_summary || job.result_code || "—"}</td>
          </tr>)}</tbody>
        </table></div>}
    </Panel>
    {selection && <div className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/45 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !createJob.isPending) setSelection(null); }}>
      <section className="w-full max-w-lg rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby="software-job-confirm-title">
        <h2 id="software-job-confirm-title" className="text-lg font-bold text-[var(--color-foreground)]">Confirm {selection.action.toLowerCase()}</h2>
        <p className="my-3 text-[11px] leading-relaxed text-[var(--color-muted)]">{selection.action === "INSTALL" ? "This will run the approved package manager on this device." : "This removes the selected application using its exact approved package identifier and may affect apps in use."} Target device: <strong>{id}</strong>. Package: <strong>{selection.pkg.display_name} ({selection.pkg.package_id})</strong>.</p>
        {selection.action === "INSTALL" && <div className="grid gap-3">
          {selection.pkg.supported_scopes.length > 1 && <label className="text-[10px] text-[var(--color-muted)]">Installation scope <select className={selectClass} value={scope} onChange={(event) => setScope(event.target.value as "MACHINE" | "USER")}>{selection.pkg.supported_scopes.map((value) => <option key={value}>{value}</option>)}</select></label>}
          <p className="text-[10px] text-[var(--color-muted)]">Version policy: {selection.pkg.version_policy}{selection.pkg.approved_version ? " · " + selection.pkg.approved_version : ""}</p>
          {selection.pkg.version_policy === "SELECTABLE" && <label className="text-[10px] text-[var(--color-muted)]">Requested version <input className={selectClass} value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.2.3" /></label>}
        </div>}
        {createJob.isError && <div role="alert" className="mt-3 text-[10px] text-red-700">{createJob.error.message}</div>}
        <div className="mt-5 flex justify-end gap-2"><Button disabled={createJob.isPending} onClick={() => setSelection(null)}>Cancel</Button>
          <Button className={selection.action === "UNINSTALL" ? "border-red-200 text-red-700" : "bg-[var(--color-primary)] text-white"} disabled={createJob.isPending || (selection.action === "INSTALL" && selection.pkg.version_policy === "SELECTABLE" && !version)} onClick={submit}>{createJob.isPending ? "Submitting…" : selection.action === "INSTALL" ? "Confirm installation" : "Confirm uninstallation"}</Button></div>
      </section>
    </div>}
  </>;
}
