import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { softwareApi } from "./api";

const inputClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";

export function SoftwareCatalogAdmin() {
  const { admin } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [displayName, setDisplayName] = useState("");
  const [packageId, setPackageId] = useState("");
  const [manager, setManager] = useState<"WINGET" | "CHOCO">("WINGET");
  const [publisher, setPublisher] = useState("");
  const [description, setDescription] = useState("");
  const [policy, setPolicy] = useState<"LATEST" | "PINNED" | "SELECTABLE">("LATEST");
  const [version, setVersion] = useState("");
  const [scopes, setScopes] = useState<Array<"MACHINE" | "USER">>(["MACHINE"]);
  const [search, setSearch] = useState("");
  const [repositorySearch, setRepositorySearch] = useState("");
  const [repositorySource, setRepositorySource] = useState("winget");
  const [managerFilter, setManagerFilter] = useState<"ALL" | "WINGET" | "CHOCO">("ALL");
  const catalog = useQuery({ queryKey: ["software-catalog", "all", search, managerFilter], queryFn: () => softwareApi.catalog({ search, ...(managerFilter === "ALL" ? {} : { package_manager: managerFilter }) }) });
  const wingetStatus = useQuery({ queryKey: ["winget-discovery-status"], queryFn: softwareApi.wingetDiscoveryStatus });
  const wingetSources = useQuery({ queryKey: ["winget-discovery-sources"], queryFn: softwareApi.wingetSources });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["software-catalog"] });
    void qc.invalidateQueries({ queryKey: ["software-jobs"] });
  };
  const create = useMutation({
    mutationFn: () => softwareApi.createCatalogPackage({
      display_name: displayName.trim(), package_id: packageId.trim(), package_manager: manager,
      publisher: publisher.trim() || undefined, description: description.trim() || undefined,
      version_policy: policy, approved_version: policy === "PINNED" ? version.trim() || undefined : undefined,
      supported_scopes: manager === "CHOCO" ? ["MACHINE"] : scopes,
    }),
    onSuccess: () => { setDisplayName(""); setPackageId(""); setPublisher(""); setDescription(""); setVersion(""); invalidate(); toast("Package added for Super Admin review."); },
    onError: (error: Error) => toast(`Catalog entry was not saved. ${error.message}`, "error"),
  });
  const approve = useMutation({ mutationFn: softwareApi.approveCatalogPackage, onSuccess: () => { invalidate(); toast("Package approved."); }, onError: (error: Error) => toast(error.message, "error") });
  const revoke = useMutation({ mutationFn: softwareApi.revokeCatalogPackage, onSuccess: () => { invalidate(); toast("Package approval revoked."); }, onError: (error: Error) => toast(error.message, "error") });
  const reject = useMutation({ mutationFn: softwareApi.rejectCatalogPackage, onSuccess: () => { invalidate(); toast("Package rejected and kept out of the deployment catalog."); }, onError: (error: Error) => toast(error.message, "error") });
  const discover = useMutation({ mutationFn: ({ query, source }: { query: string; source: string }) => softwareApi.searchWingetRepository(query, source), onError: (error: Error) => toast(`WinGet search failed. ${error.message}`, "error") });
  const importDiscovered = useMutation({
    mutationFn: ({ package_id, source }: { package_id: string; source: string }) =>
      softwareApi.importWingetPackage({ package_id, source, supported_scopes: ["MACHINE"] }),
    onSuccess: (result) => { invalidate(); toast(result.created ? "WinGet package added for approval." : "This WinGet package is already in the catalog."); },
    onError: (error: Error) => toast(`Package could not be added. ${error.message}`, "error"),
  });
  if (admin?.role !== "SUPER_ADMIN") return null;
  const toggleScope = (value: "MACHINE" | "USER") => setScopes((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  return <>
    <Panel className="mb-4">
      <PanelTitle>Discover available WinGet packages</PanelTitle>
      <p className="mt-1 text-[10px] text-[var(--color-muted)]">Search the WinGet source available to this server, then add selected packages as pending catalog entries. Client inventory remains locally collected.</p>
      {wingetStatus.data && <p className="mt-2 text-[10px] text-[var(--color-muted)]" role="status">{wingetStatus.data.available ? `Server WinGet ${wingetStatus.data.version} is available to ${wingetStatus.data.execution_identity ?? "the server process"}.` : `Server WinGet unavailable: ${wingetStatus.data.error?.message ?? "Discovery cannot run in this server context."}`}</p>}
      {wingetStatus.isError && <QueryError error={wingetStatus.error} />}
      {wingetSources.data && <p className="mt-1 text-[9px] text-[var(--color-muted)]">Configured WinGet sources: {wingetSources.data.sources.map((item) => item.name).join(", ") || "none"}</p>}
      {wingetSources.isError && <QueryError error={wingetSources.error} />}
      <form className="mt-3 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); discover.mutate({ query: repositorySearch.trim(), source: repositorySource }); }}>
        <input className={inputClass} aria-label="Search WinGet repository" placeholder="Search available packages" value={repositorySearch} onChange={(event) => setRepositorySearch(event.target.value)} maxLength={128} required />
        <select className={inputClass} aria-label="WinGet source" value={repositorySource} onChange={(event) => setRepositorySource(event.target.value)} disabled={!wingetSources.data?.sources.length}>{(wingetSources.data?.sources.length ? wingetSources.data.sources : [{ name: "winget" }]).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
        <Button disabled={!repositorySearch.trim() || discover.isPending || wingetStatus.data?.available === false}>{discover.isPending ? "Searching…" : "Search WinGet repository"}</Button>
      </form>
      {discover.isError && <QueryError error={discover.error} />}
      {discover.data && <div className="mt-3">
        <p className="text-[9px] text-[var(--color-muted)]">{discover.data.results.length} result(s) from {discover.data.source} · WinGet {discover.data.winget_version}</p>
        {discover.data.results.length === 0 ? <p className="pt-2 text-[10px] text-[var(--color-muted)]">No available packages matched that search.</p> : <div className="divide-y divide-[var(--color-border)]">{discover.data.results.map((result) => {
          const existing = catalog.data?.find((pkg) => pkg.package_manager === "WINGET" && pkg.package_id.toLowerCase() === result.package_id.toLowerCase());
          return <div className="flex flex-wrap items-center justify-between gap-3 py-2" key={`${result.source}:${result.package_id}`}>
            <div><strong className="block text-[10px] text-[var(--color-foreground)]">{result.name}</strong><span className="text-[9px] text-[var(--color-muted)]">{result.package_id} · {result.version ?? "Version unavailable"} · {result.source}</span></div>
            {existing || result.catalog_status ? <span className="text-[9px] text-[var(--color-muted)]">In catalog · {existing?.approval_status ?? result.catalog_status}</span> : result.source.toLowerCase() !== "winget" ? <span className="text-[9px] text-[var(--color-muted)]">Search only · client deployment currently uses the winget source</span> : <Button disabled={importDiscovered.isPending} onClick={() => importDiscovered.mutate({ package_id: result.package_id, source: result.source })}>Add for approval</Button>}
          </div>;
        })}</div>}
      </div>}
    </Panel>
    <Panel className="mb-4">
      <PanelTitle>Software approval catalog</PanelTitle>
      <p className="mt-1 text-[10px] text-[var(--color-muted)]">Only reviewed package identifiers can be deployed. Adding a package does not approve it.</p>
      <form className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <input className={inputClass} aria-label="Application name" placeholder="Application name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
        <input className={inputClass} aria-label="Exact package ID" placeholder="Exact package ID" value={packageId} onChange={(event) => setPackageId(event.target.value)} required />
        <select className={inputClass} aria-label="Package manager" value={manager} onChange={(event) => { const next = event.target.value as "WINGET" | "CHOCO"; setManager(next); if (next === "CHOCO") setScopes(["MACHINE"]); }}><option value="WINGET">WinGet Community</option><option value="CHOCO">Configured Chocolatey</option></select>
        <input className={inputClass} aria-label="Publisher" placeholder="Publisher (optional)" value={publisher} onChange={(event) => setPublisher(event.target.value)} />
        <input className={`${inputClass} sm:col-span-2`} aria-label="Description" placeholder="Description (optional)" value={description} onChange={(event) => setDescription(event.target.value)} />
        <select className={inputClass} aria-label="Version policy" value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)}><option value="LATEST">Latest</option><option value="PINNED">Pinned</option><option value="SELECTABLE">Selectable</option></select>
        {policy === "PINNED" && <input className={inputClass} aria-label="Pinned version" placeholder="Pinned version" value={version} onChange={(event) => setVersion(event.target.value)} required />}
        {policy === "SELECTABLE" && <p className="text-[9px] text-[var(--color-muted)]">Administrators choose a validated version when creating each install job.</p>}
        {manager === "WINGET" && <fieldset className="flex items-center gap-3 text-[10px] text-[var(--color-muted)]"><legend>Supported scope</legend>{(["MACHINE", "USER"] as const).map((value) => <label key={value} className="flex items-center gap-1"><input type="checkbox" checked={scopes.includes(value)} onChange={() => toggleScope(value)} />{value}</label>)}</fieldset>}
        <Button disabled={create.isPending || !scopes.length || (policy === "PINNED" && !version.trim())}>{create.isPending ? "Adding…" : "Add for review"}</Button>
      </form>
      {create.isError && <QueryError error={create.error} />}
    </Panel>
    <Panel className="mb-4">
      <PanelTitle>Catalog entries</PanelTitle>
      <div className="my-3 flex flex-wrap gap-2"><input className={inputClass} aria-label="Search catalog entries" placeholder="Search name or package ID" value={search} onChange={(event) => setSearch(event.target.value)} /><select className={inputClass} aria-label="Filter catalog manager" value={managerFilter} onChange={(event) => setManagerFilter(event.target.value as typeof managerFilter)}><option value="ALL">All managers</option><option value="WINGET">WinGet</option><option value="CHOCO">Chocolatey</option></select></div>
      {catalog.isError && <QueryError error={catalog.error} />}
      {catalog.isLoading ? <Loading label="Loading package catalog…" /> : <div className="divide-y divide-[var(--color-border)]">{(catalog.data ?? []).map((pkg) => <div className="flex flex-wrap items-center justify-between gap-3 py-3" key={pkg.id}>
        <div className="min-w-0"><strong className="block text-[11px] text-[var(--color-foreground)]">{pkg.display_name}</strong><span className="text-[9px] text-[var(--color-muted)]">{pkg.package_id} · {pkg.package_manager} · {pkg.source} · {pkg.version_policy}{pkg.approved_version ? ` ${pkg.approved_version}` : ""}</span><span className="block text-[9px] text-[var(--color-muted)]">{pkg.publisher || "Publisher unavailable"} · Scopes: {pkg.supported_scopes.join(", ")}</span>{pkg.description && <span className="block max-w-3xl text-[9px] text-[var(--color-muted)]">{pkg.description}</span>}<span className="block text-[9px] font-semibold text-[var(--color-muted)]">Review status: {pkg.approval_status}</span></div>
        <div className="flex gap-2">{pkg.approved ? <Button className="border-red-200 text-red-700" disabled={revoke.isPending} onClick={() => revoke.mutate(pkg.id)}>Revoke approval</Button> : <><Button disabled={approve.isPending} onClick={() => approve.mutate(pkg.id)}>Approve package</Button>{pkg.approval_status !== "REJECTED" && <Button className="border-red-200 text-red-700" disabled={reject.isPending} onClick={() => reject.mutate(pkg.id)}>Reject</Button>}</>}</div>
      </div>)}</div>}
      {(approve.isError || revoke.isError || reject.isError) && <p role="alert" className="mt-2 text-[10px] text-red-700">{approve.error?.message ?? revoke.error?.message ?? reject.error?.message}</p>}
    </Panel>
  </>;
}
