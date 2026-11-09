import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { Link } from "react-router-dom";
import { Empty, PageHeader, Panel, QueryError, Skeleton } from "../../components/ui";
import { devicesApi } from "./api";

export function ProcessMonitoringPage() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });

  return (
    <>
      <PageHeader
        eyebrow="MONITORING"
        title="Process Monitoring"
        description="Choose a device to request its current process list. Process details are collected on demand."
      />
      {devices.isError && <QueryError error={devices.error} />}
      <Panel>
        {devices.isLoading ? (
          <Skeleton rows={5} />
        ) : devices.data?.length ? (
          <div className="divide-y divide-[var(--color-border)]">
            {devices.data.map((device) => (
              <Link
                key={device.id}
                to={`/devices/${device.id}?tab=Processes`}
                className="flex items-center justify-between gap-3 p-4 transition hover:bg-[var(--color-surface-subtle)]"
              >
                <span>
                  <span className="block text-[11px] font-semibold text-[var(--color-foreground)]">
                    {device.assigned_name || device.hostname}
                  </span>
                  <span className="mt-1 block text-[10px] text-[var(--color-muted)]">
                    {device.assigned_name ? device.hostname : device.id}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1.5 text-[10px] text-[var(--color-primary)]">
                  <Activity size={14} /> View processes
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <Empty title="No devices registered" detail="Enroll a device to inspect its processes." />
        )}
      </Panel>
    </>
  );
}
