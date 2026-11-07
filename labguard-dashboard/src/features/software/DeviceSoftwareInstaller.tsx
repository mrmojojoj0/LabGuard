import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import type { SoftwareCatalogPackage, WingetDiscoveryResult } from "../../lib/types";
import { softwareApi } from "./api";

type Selection =
  | { kind: "WINGET"; pkg: WingetDiscoveryResult }
  | { kind: "CHOCO"; pkg: SoftwareCatalogPackage };

const inputClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";

export function DeviceSoftwareInstaller({ deviceId }: { deviceId: string }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"MACHINE" | "USER">("MACHINE");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(null);
  const refreshHandled = useRef(false);
  const search = useMutation({
    mutationFn: (value: string) => softwareApi.searchWingetRepository(value, "winget"),
    onError: (error: Error) => toast(`WinGet search failed. ${error.message}`, "error"),
  });
  const chocolatey = useQuery({
    queryKey: ["software-catalog", "approved-chocolatey"],
    queryFn: () => softwareApi.catalog({ package_manager: "CHOCO", approved: true }),
  });
  const details = useQuery({
    queryKey: ["winget-package-details", selection?.kind === "WINGET" ? selection.pkg.package_id : null],
    queryFn: () => softwareApi.wingetPackageDetails((selection as Extract<Selection, { kind: "WINGET" }>).pkg.package_id),
    enabled: selection?.kind === "WINGET",
    retry: false,
  });
  const jobs = useQuery({
    queryKey: ["software-jobs", deviceId],
    queryFn: () => softwareApi.jobs(deviceId),
    refetchInterval: 3000,
  });
  const createJob = useMutation({
    mutationFn: () => selection?.kind === "CHOCO"
      ? softwareApi.createJob(deviceId, { action: "INSTALL", catalog_package_id: selection.pkg.id, installation_scope: "MACHINE" })
      : softwareApi.createJob(deviceId, {
        action: "INSTALL",
        package_manager: "WINGET",
        package_id: selection!.pkg.package_id,
        source: "winget",
        installation_scope: scope,
        ...((selection as Extract<Selection, { kind: "WINGET" }>).pkg.version
          ? { version: (selection as Extract<Selection, { kind: "WINGET" }>).pkg.version! }
          : {}),
      }),
    onSuccess: (job) => {
      refreshHandled.current = false;
      setSubmittedJobId(job.id);
      setSelection(null);
      toast("Installation queued for this device.");
      void qc.invalidateQueries({ queryKey: ["software-jobs", deviceId] });
    },
    onError: (error: Error) => toast(`Installation was not queued. ${error.message}`, "error"),
  });
  const submittedJob = jobs.data?.items.find((job) => job.id === submittedJobId);

  useEffect(() => {
    if (submittedJob?.status === "SUCCEEDED" && !refreshHandled.current) {
      refreshHandled.current = true;
      void softwareApi.refresh(deviceId).then(() => {
        void qc.invalidateQueries({ queryKey: ["device-software", deviceId] });
        toast("Installation verified; inventory refresh requested.");
      }).catch((error: Error) => toast(`Installed, but inventory refresh failed. ${error.message}`, "error"));
    }
  }, [submittedJob?.status, deviceId, qc, toast]);

  return <>
    <Panel className="mb-4">
      <PanelTitle>Install software on this device</PanelTitle>
      <p className="mb-2 text-[9px] text-[var(--color-muted)]">Search the fixed WinGet community source, or choose an existing approved Chocolatey package.</p>
      <form className="my-3 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); search.mutate(query.trim()); }}>
        <input className={`${inputClass} min-w-64 flex-1`} aria-label="Device WinGet search" placeholder="Search package name" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={128} required />
        <Button disabled={!query.trim() || search.isPending}>{search.isPending ? "Searching…" : "Search WinGet"}</Button>
      </form>
      {search.isError && <QueryError error={search.error} />}
      {search.data && <div className="divide-y divide-[var(--color-border)]" aria-live="polite">
        {!search.data.results.length ? <p className="py-2 text-[10px] text-[var(--color-muted)]">No packages matched.</p> : search.data.results.map((pkg) => <div className="flex flex-wrap items-center justify-between gap-3 py-2" key={`${pkg.source}:${pkg.package_id}`}>
          <span className="text-[10px] text-[var(--color-foreground)]">{pkg.name} <span className="text-[var(--color-muted)]">· {pkg.package_id} · {pkg.version || "Latest"}</span></span>
          <Button onClick={() => { setScope("MACHINE"); setSelection({ kind: "WINGET", pkg }); }}>Install</Button>
        </div>)}
      </div>}
      {chocolatey.isError && <QueryError error={chocolatey.error} />}
      {chocolatey.isLoading ? <Loading label="Loading approved Chocolatey packages…" /> : chocolatey.data?.length ? <div className="mt-2 divide-y divide-[var(--color-border)]">
        {chocolatey.data.map((pkg) => <div className="flex flex-wrap items-center justify-between gap-3 py-2" key={pkg.id}>
          <span className="text-[10px] text-[var(--color-foreground)]">{pkg.display_name} <span className="text-[var(--color-muted)]">· {pkg.package_id} · machine scope</span></span>
          <Button onClick={() => setSelection({ kind: "CHOCO", pkg })}>Install Chocolatey package</Button>
        </div>)}
      </div> : <p className="text-[9px] text-[var(--color-muted)]">No approved Chocolatey packages are available.</p>}
    </Panel>
    <Panel className="mb-4">
      <PanelTitle>Recent jobs for this device</PanelTitle>
      {jobs.isError && <QueryError error={jobs.error} />}
      {jobs.isLoading ? <Loading label="Loading device software jobs…" /> : !jobs.data?.items.length ? <p className="pt-2 text-[10px] text-[var(--color-muted)]">No software jobs for this device.</p> : <div className="divide-y divide-[var(--color-border)]">
        {jobs.data.items.slice(0, 5).map((job) => <div className="flex flex-wrap justify-between gap-2 py-2 text-[10px]" key={job.id}>
          <span className="font-semibold text-[var(--color-foreground)]">{job.action} {job.package_id}</span>
          <span className="text-[var(--color-muted)]">{job.status} · {job.progress_percent}%{job.progress_message ? ` · ${job.progress_message}` : ""}{job.error_message ? ` · ${job.error_message}` : ""}</span>
        </div>)}
      </div>}
    </Panel>
    {selection && <div className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/45 p-4" role="presentation">
      <section className="w-full max-w-lg rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby="device-install-title">
        <h2 id="device-install-title" className="text-lg font-bold text-[var(--color-foreground)]">Confirm installation</h2>
        {selection.kind === "WINGET" && details.isLoading ? <Loading label="Verifying exact WinGet package…" /> : selection.kind === "WINGET" && details.isError ? <QueryError error={details.error} /> : <>
          <p className="my-3 text-[11px] text-[var(--color-muted)]">{selection.kind === "WINGET" ? details.data?.display_name : selection.pkg.display_name} · {selection.pkg.package_id} · {selection.kind === "WINGET" ? selection.pkg.version || details.data?.version || "latest" : selection.pkg.version_policy} · {selection.kind === "WINGET" ? details.data?.publisher || "Publisher unavailable" : selection.pkg.publisher || "Publisher unavailable"}</p>
          {selection.kind === "WINGET" ? <label className="text-[10px] text-[var(--color-muted)]">Installation scope <select aria-label="Device installation scope" className={`${inputClass} ml-2`} value={scope} onChange={(event) => setScope(event.target.value as "MACHINE" | "USER")}><option value="MACHINE">Machine</option><option value="USER">Current user (foreground agent only)</option></select></label> : <p className="text-[10px] text-[var(--color-muted)]">Installation scope: machine</p>}
        </>}
        {createJob.isError && <div role="alert" className="mt-3 text-[10px] text-red-700">{createJob.error.message}</div>}
        <div className="mt-5 flex justify-end gap-2"><Button disabled={createJob.isPending} onClick={() => setSelection(null)}>Cancel</Button><Button className="bg-[var(--color-primary)] text-white" disabled={(selection.kind === "WINGET" && (details.isLoading || details.isError)) || createJob.isPending} onClick={() => createJob.mutate()}>{createJob.isPending ? "Submitting…" : "Confirm installation"}</Button></div>
      </section>
    </div>}
  </>;
}
