import { useQuery } from "@tanstack/react-query";
import { Loading, PageHeader, Panel, PanelTitle, QueryError } from "../../components/ui";
import { devicesApi } from "../devices/api";
import { SoftwareCatalogAdmin } from "./SoftwareCatalogAdmin";
import { softwareApi } from "./api";

export function SoftwareDeploymentPage() {
  const jobs = useQuery({ queryKey: ["software-jobs"], queryFn: () => softwareApi.jobs(), refetchInterval: 3000 });
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const names = new Map((devices.data ?? []).map((device) => [device.id, device.assigned_name || device.hostname]));
  return <>
    <PageHeader eyebrow="SOFTWARE OPERATIONS" title="Software Deployment" description="Review approved packages and monitor individual install or uninstall requests." />
    <SoftwareCatalogAdmin />
    <Panel>
      <PanelTitle>Deployment jobs <span className="text-[9px] font-normal text-[var(--color-muted)]">{jobs.data?.total ?? 0} recent</span></PanelTitle>
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
  </>;
}
