import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Button, Empty, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import { softwareApi } from "./api";
import { SoftwareManagementControls } from "./SoftwareManagementControls";

export function DeviceSoftware({ id }: { id: string }) {
  const qc = useQueryClient();
  const { admin } = useAuth();
  const toast = useToast();
  const queryKey = ["device-software", id];
  const result = useQuery({ queryKey, queryFn: () => softwareApi.device(id) });
  const refresh = useMutation({
    mutationFn: () => softwareApi.refresh(id),
    onSuccess: () => {
      toast("Inventory refresh requested.");
      void qc.invalidateQueries({ queryKey });
    },
    onError: (error: Error) => toast(`Inventory refresh failed. ${error.message}`, "error"),
  });
  const collection = result.data?.collection;
  const successfulAt = collection?.last_successful_at;
  const stale = collection?.stale;
  return <>
  <Panel>
    <PanelTitle aside={canManageLabs(admin?.role) ? <Button disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw size={13} className={refresh.isPending ? "animate-spin" : ""}/>{refresh.isPending ? "Requesting…" : "Refresh inventory"}</Button> : undefined}>Installed software</PanelTitle>
    <div className="my-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg bg-[var(--color-surface-subtle)] p-3 text-[10px]">
      <span><b className="text-[var(--color-foreground)]">Collection:</b> <span className="text-[var(--color-muted)]">{collection?.status ?? "Loading"}</span></span>
      <span><b className="text-[var(--color-foreground)]">Last attempt:</b> <span className="text-[var(--color-muted)]">{collection?.last_attempt_at ? new Date(collection.last_attempt_at).toLocaleString() : "Never"}</span></span>
      <span><b className="text-[var(--color-foreground)]">Last successful:</b> <span className="text-[var(--color-muted)]">{successfulAt ? new Date(successfulAt).toLocaleString() : "Never"}</span></span>
      <span><b className="text-[var(--color-foreground)]">Last complete:</b> <span className="text-[var(--color-muted)]">{collection?.last_complete_at ? new Date(collection.last_complete_at).toLocaleString() : "Never"}</span></span>
      <span className={`font-semibold ${stale ? "text-amber-600" : "text-emerald-600"}`}>{stale ? "Stale inventory" : collection?.status === "NEVER" ? "No inventory yet" : collection?.status === "FAILED" ? "Latest attempt failed; showing last successful snapshot" : collection?.status === "PARTIAL" ? "Current partial inventory" : "Current"}</span>
      {Boolean(collection?.errors.length) && <span className="text-amber-700">Partial collection: {collection?.errors.join(", ")}</span>}
    </div>
    {result.isError && <QueryError error={result.error}/>}
    {result.isLoading ? <Loading label="Loading device software…"/> : !result.data?.items.length ? <Empty title="No installed software reported" detail="The agent reports inventory after authentication and on its configured schedule."/> : <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-[10px]"><thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">{["Application", "Version", "Publisher", "Architecture", "Installed", "Scope / source"].map((item) => <th className="px-2 py-2 font-semibold" key={item}>{item}</th>)}</tr></thead><tbody>{result.data.items.map((item) => <tr className="border-b border-[var(--color-border)] last:border-0" key={item.id}><td className="px-2 py-3 font-semibold text-[var(--color-foreground)]">{item.name}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.version || "—"}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.publisher || "—"}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.architecture}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.install_date || "—"}</td><td className="px-2 py-3 text-[var(--color-muted)]">{item.installation_scope} · {item.source}</td></tr>)}</tbody></table></div>}
    {collection?.status === "IN_PROGRESS" && <p className="mt-3 text-[9px] text-[var(--color-muted)]">A scan is still running. The list updates when the collection completes.</p>}
  </Panel>
  <SoftwareManagementControls id={id} items={result.data?.items ?? []} />
  </>;
}
