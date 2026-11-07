import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import type { SoftwareCatalogPackage } from "../../lib/types";
import { softwareApi } from "./api";

type Selection = { action: "INSTALL"; pkg: SoftwareCatalogPackage };
const selectClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";

export function SoftwareManagementControls({ id }: { id: string }) {
  const { admin } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [repositorySearch, setRepositorySearch] = useState("");
  const [repositorySource, setRepositorySource] = useState("winget");
  const [importedPackages, setImportedPackages] = useState<Record<string, string>>({});
  const [manager, setManager] = useState<"ALL" | "WINGET" | "CHOCO">("ALL");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [scope, setScope] = useState<"MACHINE" | "USER">("MACHINE");
  const [version, setVersion] = useState("");
  const catalog = useQuery({ queryKey: ["software-catalog", search, manager], queryFn: () => softwareApi.catalog({ search, approved: true, ...(manager === "ALL" ? {} : { package_manager: manager }) }) });
  const canDiscover = admin?.role === "SUPER_ADMIN";
  const wingetSources = useQuery({
    queryKey: ["winget-discovery-sources"],
    queryFn: softwareApi.wingetSources,
    enabled: canDiscover,
  });
  const searchRepository = useMutation({
    mutationFn: ({ query, source }: { query: string; source: string }) =>
      softwareApi.searchWingetRepository(query, source),
    onError: (error: Error) => toast("WinGet repository search failed. " + error.message, "error"),
  });
  const importDiscovered = useMutation({
    mutationFn: ({ package_id, source }: { package_id: string; source: string }) =>
      softwareApi.importWingetPackage({ package_id, source, supported_scopes: ["MACHINE"] }),
    onSuccess: (result) => {
      setImportedPackages((current) => ({ ...current, [result.package.package_id.toLowerCase()]: result.package.approval_status }));
      void qc.invalidateQueries({ queryKey: ["software-catalog"] });
      toast(result.created ? "WinGet package added for Super Admin approval. Review it in Software Deployment." : "This WinGet package is already in the catalog.");
    },
    onError: (error: Error) => toast("Package could not be imported. " + error.message, "error"),
  });
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
  const canManage = canManageLabs(admin?.role);
  const submit = () => {
    if (!selection) return;
    const body = {
      action: "INSTALL" as const, catalog_package_id: selection.pkg.id,
      installation_scope: scope,
      ...(selection.pkg.version_policy === "SELECTABLE" ? { version } : {}),
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
      {canDiscover && <section className="mb-4 rounded-lg border border-[var(--color-border)] p-3" aria-label="WinGet repository discovery">
        <h3 className="text-[11px] font-semibold text-[var(--color-foreground)]">Search WinGet Repository</h3>
        <p className="mt-1 text-[9px] text-[var(--color-muted)]">This searches packages available from the server's WinGet source. Results are separate from the approved packages below.</p>
        {wingetSources.isLoading && <Loading label="Loading WinGet sources…" />}
        {wingetSources.isError && <QueryError error={wingetSources.error} />}
        {wingetSources.data && <form className="mt-2 flex flex-wrap gap-2" onSubmit={(event) => {
          event.preventDefault();
          const sources = wingetSources.data?.sources ?? [];
          const source = sources.some((item) => item.name === repositorySource) ? repositorySource : sources[0]?.name ?? "winget";
          searchRepository.mutate({ query: repositorySearch.trim(), source });
        }}>
          <input className={selectClass} aria-label="WinGet repository search text" placeholder="Search available WinGet packages" value={repositorySearch} onChange={(event) => setRepositorySearch(event.target.value)} maxLength={128} required />
          <select className={selectClass} aria-label="WinGet repository source" value={repositorySource} onChange={(event) => setRepositorySource(event.target.value)}>
            {wingetSources.data.sources.map((source) => <option key={source.name} value={source.name}>{source.name}</option>)}
          </select>
          <Button disabled={!repositorySearch.trim() || searchRepository.isPending}>{searchRepository.isPending ? "Searching…" : "Search WinGet Repository"}</Button>
        </form>}
        {searchRepository.isPending && <Loading label="Searching the WinGet repository…" />}
        {searchRepository.isError && <QueryError error={searchRepository.error} />}
        {searchRepository.data && <div className="mt-3" aria-live="polite">
          <p className="text-[9px] text-[var(--color-muted)]">{searchRepository.data.results.length} result(s) from {searchRepository.data.source} · WinGet {searchRepository.data.winget_version}</p>
          {!searchRepository.data.results.length ? <p className="pt-2 text-[10px] text-[var(--color-muted)]">No available packages matched that search.</p> :
            <div className="divide-y divide-[var(--color-border)]">{searchRepository.data.results.map((result) => {
              const importedStatus = importedPackages[result.package_id.toLowerCase()];
              const status = importedStatus ?? result.catalog_status;
              return <div className="flex flex-wrap items-center justify-between gap-3 py-2" key={result.source + ":" + result.package_id}>
                <div><strong className="block text-[10px] text-[var(--color-foreground)]">{result.name}</strong><span className="text-[9px] text-[var(--color-muted)]">{result.package_id} · {result.version ?? "Version unavailable"} · {result.source}</span></div>
                {status ? <span className="text-[9px] text-[var(--color-muted)]">{importedStatus ? "Added for approval" : "In catalog"} · {status}</span> :
                  result.source.toLowerCase() !== "winget" ? <span className="text-[9px] text-[var(--color-muted)]">Search only · client deployment currently uses the winget source</span> :
                    <Button disabled={importDiscovered.isPending} onClick={() => importDiscovered.mutate({ package_id: result.package_id, source: result.source })}>Add for approval</Button>}
              </div>;
            })}</div>}
        </div>}
      </section>}
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
        <p className="my-3 text-[11px] leading-relaxed text-[var(--color-muted)]">This will run the approved package manager on this device. Target device: <strong>{id}</strong>. Package: <strong>{selection.pkg.display_name} ({selection.pkg.package_id})</strong>.</p>
        {selection.action === "INSTALL" && <div className="grid gap-3">
          {selection.pkg.supported_scopes.length > 1 && <label className="text-[10px] text-[var(--color-muted)]">Installation scope <select className={selectClass} value={scope} onChange={(event) => setScope(event.target.value as "MACHINE" | "USER")}>{selection.pkg.supported_scopes.map((value) => <option key={value}>{value}</option>)}</select></label>}
          <p className="text-[10px] text-[var(--color-muted)]">Version policy: {selection.pkg.version_policy}{selection.pkg.approved_version ? " · " + selection.pkg.approved_version : ""}</p>
          {selection.pkg.version_policy === "SELECTABLE" && <label className="text-[10px] text-[var(--color-muted)]">Requested version <input className={selectClass} value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.2.3" /></label>}
        </div>}
        {createJob.isError && <div role="alert" className="mt-3 text-[10px] text-red-700">{createJob.error.message}</div>}
        <div className="mt-5 flex justify-end gap-2"><Button disabled={createJob.isPending} onClick={() => setSelection(null)}>Cancel</Button>
          <Button className="bg-[var(--color-primary)] text-white" disabled={createJob.isPending || (selection.pkg.version_policy === "SELECTABLE" && !version)} onClick={submit}>{createJob.isPending ? "Submitting…" : "Confirm installation"}</Button></div>
      </section>
    </div>}
  </>;
}
