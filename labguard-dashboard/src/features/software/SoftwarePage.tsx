import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { softwareApi } from "./api";
import { devicesApi } from "../devices/api";
import type { SoftwareAggregate } from "../../lib/types";
import { Empty, Loading, PageHeader, Panel, PanelTitle, QueryError } from "../../components/ui";

const selectClass = "h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)]";

export function SoftwarePage() {
  const [search, setSearch] = useState("");
  const [publisher, setPublisher] = useState("");
  const [source, setSource] = useState("");
  const [scope, setScope] = useState("");
  const [version, setVersion] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Pick<SoftwareAggregate, "software_key" | "name" | "publisher"> | null>(null);
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
      ].map(([label, value]) => <Panel key={label}><p className="text-[9px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">{label}</p><strong className="mt-2 block text-2xl text-[var(--color-foreground)]">{value ?? "—"}</strong></Panel>)}
    </div>
    <Panel className="mb-4">
      <PanelTitle>Most commonly installed <span className="text-[9px] font-normal text-[var(--color-muted)]">· {summary.data?.collecting_devices ?? 0} collecting · {summary.data?.partial_devices ?? 0} partial</span></PanelTitle>
      <div className="mt-3 flex flex-wrap gap-2">{summary.data?.most_common.map((item) => <button key={item.software_key} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-2 text-left" onClick={() => setSelected(item)}><strong className="block text-[10px] text-[var(--color-foreground)]">{item.name}</strong><span className="text-[9px] text-[var(--color-muted)]">{item.installation_count} installations on {item.device_count} devices</span></button>)}</div>
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
      {result.isLoading ? <Loading label="Loading software inventory…" /> : !result.data?.items.length ? <Empty title="No software inventory found" detail="Try changing the filters or wait for an enrolled device to report inventory." /> : <>
        <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-[10px]"><thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">{["Application", "Publisher", "Installations", "Source"].map((label) => <th className="px-2 py-2 font-semibold" key={label}>{label}</th>)}</tr></thead><tbody>{result.data.items.map((item) => <tr className="border-b border-[var(--color-border)] last:border-0" key={item.software_key}><td className="px-2 py-3"><button className="text-left font-semibold text-[var(--color-primary)] hover:underline" onClick={() => setSelected(item)}>{item.name}</button></td><td className="px-2 py-3 text-[var(--color-muted)]">{item.publisher ?? "—"}</td><td className="px-2 py-3 text-[var(--color-foreground)]">{item.installation_count} on {item.device_count} devices</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.source}</td></tr>)}</tbody></table></div>
        <div className="mt-3 flex items-center justify-between text-[10px] text-[var(--color-muted)]"><span>Page {page + 1} of {Math.max(1, Math.ceil(result.data.total / 50))}</span><div className="flex gap-2"><button className={selectClass} disabled={!page} onClick={() => setPage(page - 1)}>Previous</button><button className={selectClass} disabled={(page + 1) * 50 >= result.data.total} onClick={() => setPage(page + 1)}>Next</button></div></div>
      </>}
    </Panel>
    {selected && <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/35" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelected(null); }}><aside className="h-full w-full max-w-xl overflow-y-auto border-l border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" aria-label={`${selected.name} installations`}><div className="flex items-start justify-between"><div><p className="text-[9px] font-bold uppercase tracking-wider text-[var(--color-muted)]">APPLICATION</p><h2 className="my-1 text-xl font-bold text-[var(--color-foreground)]">{selected.name}</h2><p className="text-[10px] text-[var(--color-muted)]">{selected.publisher ?? "Publisher unavailable"}</p></div><button className="rounded p-2 text-[var(--color-muted)]" aria-label="Close installations" onClick={() => setSelected(null)}><X size={18}/></button></div><h3 className="mt-7 border-b border-[var(--color-border)] pb-2 text-xs font-bold text-[var(--color-foreground)]">Installed on</h3>{installations.isError && <QueryError error={installations.error}/ >}{installations.isLoading ? <Loading label="Loading device installations…"/> : <div className="divide-y divide-[var(--color-border)]">{installations.data?.items.map((item) => <div className="py-3" key={item.id}><strong className="block text-[11px] text-[var(--color-foreground)]">{item.device_name || item.hostname || item.device_id}</strong><span className="text-[9px] text-[var(--color-muted)]">{item.version || "Version unavailable"} · {item.source} · {item.installation_scope.toLowerCase()}</span></div>)}</div>}</aside></div>}
  </>;
}
