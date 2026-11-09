import { useQuery } from "@tanstack/react-query";
import { Cpu, MemoryStick, HardDrive, Activity } from "lucide-react";
import { devicesApi } from "./api";
import { Panel, PanelTitle, QueryError, Skeleton } from "../../components/ui";
import type { TelemetrySample, TelemetrySnapshot } from "../../lib/types";

function formatBytes(value: number) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit++;
  }
  return `${amount.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function formatUptime(value: number) {
  if (!Number.isFinite(value) || value < 0) return "Unavailable";
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return `${days}d ${hours}h ${minutes}m`;
}

export function OperatingSystemUptime({ data }: { data: TelemetrySnapshot | null | undefined }) {
  if (!data) {
    return (
      <Panel>
        <PanelTitle>Operating system &amp; uptime</PanelTitle>
        <p className="py-3 text-[9px] text-[var(--color-muted)]">Waiting for the first telemetry report.</p>
      </Panel>
    );
  }
  const os = data.operating_system;
  const rows: Array<[string, string]> = [
    ["Windows edition", os.edition || "Unavailable"],
    ["Version", os.version || "Unavailable"],
    ["Build", os.build_number || "Unavailable"],
    ["Architecture", os.architecture || "Unavailable"],
    ["Hostname", os.hostname || "Unavailable"],
    ["Uptime", formatUptime(data.uptime_seconds)],
    ["Boot time", new Date(data.boot_time).toLocaleString()],
  ];
  return (
    <Panel>
      <PanelTitle>Operating system &amp; uptime</PanelTitle>
      <div className="grid">
        {rows.map(([label, value], index) => (
          <div
            className={`flex justify-between gap-3 py-2.5 text-[10px] ${index < rows.length - 1 ? "border-b border-[var(--color-border)]" : ""}`}
            key={label}
          >
            <span className="text-[var(--color-muted)]">{label}</span>
            <strong className="text-right text-[var(--color-foreground)]">{value}</strong>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function NetworkInterfaces({ data }: { data: TelemetrySnapshot | null | undefined }) {
  const connections = data?.network_connections;
  return (
    <Panel>
      <PanelTitle>Network activity</PanelTitle>
      {!data ? (
        <p className="py-3 text-[9px] text-[var(--color-muted)]">Waiting for the first telemetry report.</p>
      ) : connections == null ? (
        <p className="py-3 text-[9px] text-[var(--color-muted)]">No network connection snapshot is available from this endpoint.</p>
      ) : connections.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-[10px]">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
                <th className="p-2">Time</th><th className="p-2">Direction</th><th className="p-2">Domain / IP</th>
                <th className="p-2">Type</th><th className="p-2">Interface</th><th className="p-2">Local endpoint</th>
                <th className="p-2">Remote endpoint</th><th className="p-2">State</th>
              </tr>
            </thead>
            <tbody>
              {connections.map((connection, index) => (
                <tr className="border-b border-[var(--color-border)] last:border-0" key={`${connection.protocol}:${connection.local_ip}:${connection.local_port}:${connection.remote_ip}:${connection.remote_port}:${index}`}>
                  <td className="whitespace-nowrap p-2">{new Date(connection.observed_at).toLocaleString()}</td>
                  <td className="p-2">{connection.direction.toLowerCase()}</td>
                  <td className="p-2 font-mono">{connection.remote_ip ?? connection.local_ip}</td>
                  <td className="p-2">{connection.protocol}</td>
                  <td className="p-2">{connection.interface}</td>
                  <td className="p-2 font-mono">{connection.local_ip}:{connection.local_port}</td>
                  <td className="p-2 font-mono">{connection.remote_ip ? `${connection.remote_ip}:${connection.remote_port ?? ""}` : "—"}</td>
                  <td className="p-2">{connection.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[8px] text-[var(--color-muted)]">Active TCP/UDP connection snapshots update with telemetry, about every 30 seconds. Packet headers and payloads are not collected.</p>
        </div>
      ) : (
        <p className="py-3 text-[9px] text-[var(--color-muted)]">No active network connections were reported.</p>
      )}
    </Panel>
  );
}
function MetricChart({
  title,
  values,
  color,
}: {
  title: string;
  values: number[];
  color: string;
}) {
  if (values.length < 2)
    return (
      <div className="min-w-0 rounded-lg border border-[var(--color-border)] p-2.5">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-[9px] text-[var(--color-foreground)]">
            {title}
          </strong>
          <span className="text-[8px] text-[var(--color-muted)]">
            History appears after two reports
          </span>
        </div>
        <div className="mt-2 grid h-[92px] place-items-center rounded-md bg-[var(--color-surface-subtle)] text-[8px] text-[var(--color-muted)]">
          Collecting history
        </div>
      </div>
    );
  const width = 320;
  const height = 92;
  const pad = 8;
  const points = values
    .map((value, index) => {
      const x = pad + (index * (width - pad * 2)) / (values.length - 1);
      const y =
        height -
        pad -
        (Math.min(100, Math.max(0, value)) * (height - pad * 2)) / 100;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <div className="min-w-0 rounded-lg border border-[var(--color-border)] p-2.5">
      <div className="flex items-center justify-between gap-2">
        <strong className="text-[9px] text-[var(--color-foreground)]">
          {title}
        </strong>
        <span className="text-[8px] text-[var(--color-muted)]">
          {values.at(-1)?.toFixed(1)}%
        </span>
      </div>
      <svg
        className="mt-2 block h-[92px] w-full overflow-visible"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title} historical utilization`}
      >
        <line
          className="stroke-[var(--color-border)] [stroke-dasharray:3_4]"
          x1={pad}
          x2={width - pad}
          y1={height / 2}
          y2={height / 2}
        />
        <polyline
          points={points}
          style={{ stroke: color }}
          className="fill-none stroke-[2.5] [stroke-linecap:round] [stroke-linejoin:round]"
        />
      </svg>
      <small className="mt-1 block text-[8px] text-[var(--color-muted)]">
        Recent reports · last {values.length}
      </small>
    </div>
  );
}

export function SystemTelemetry({ id }: { id: string }) {
  const latest = useQuery({
    queryKey: ["telemetry", id],
    queryFn: () => devicesApi.telemetry(id),
    refetchInterval: 30_000,
  });
  const history = useQuery({
    queryKey: ["telemetry-history", id],
    queryFn: () => devicesApi.telemetryHistory(id),
    refetchInterval: 30_000,
  });
  const data = latest.data?.snapshot;
  const samples: TelemetrySample[] = history.data?.samples ?? [];
  const totalBytes =
    data?.storage_partitions.reduce((sum, item) => sum + item.total_bytes, 0) ??
    0;
  const usedBytes =
    data?.storage_partitions.reduce((sum, item) => sum + item.used_bytes, 0) ??
    0;
  const diskPercent = totalBytes ? (usedBytes / totalBytes) * 100 : null;
  if (latest.isError)
    return (
      <Panel>
        <PanelTitle>System telemetry</PanelTitle>
        <QueryError error={latest.error} />
      </Panel>
    );
  if (latest.isLoading)
    return (
      <Panel>
        <PanelTitle>System telemetry</PanelTitle>
        <Skeleton rows={4} />
      </Panel>
    );
  if (!data)
    return (
      <Panel>
        <PanelTitle>System telemetry</PanelTitle>
        <div className="flex flex-col items-center gap-2 p-6 text-center text-[var(--color-muted)]">
          <Activity size={18} className="text-[var(--color-primary)]" />
          <strong className="text-[10px] text-[var(--color-foreground)]">
            Waiting for the first telemetry report
          </strong>
          <span className="text-[9px]">
            Metrics appear after the agent connects and completes its initial
            collection.
          </span>
        </div>
      </Panel>
    );
  return (
    <div className="mt-3.5 grid gap-3.5">
      <Panel>
        <PanelTitle
          aside={
            <span
              className={`rounded-full px-2 py-1 text-[8px] font-bold tracking-[.5px] ${latest.data?.stale ? "bg-[var(--color-warning-soft)] text-[var(--color-warning)]" : "bg-[var(--color-success-soft)] text-[var(--color-success)]"}`}
            >
              {latest.data?.stale ? "STALE" : "CURRENT"}
            </span>
          }
        >
          System overview
        </PanelTitle>
        <div className="mb-3.5 mt-[-5px] text-[9px] text-[var(--color-muted)]">
          Last update received {new Date(data.received_at).toLocaleString()}
          {latest.data?.stale
            ? ` · older than ${latest.data.stale_after_seconds}s`
            : ""}
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="grid grid-cols-[20px_1fr] items-center gap-x-2 gap-y-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-subtle)] p-3">
            <Cpu size={16} className="row-span-2 text-[var(--color-primary)]" />
            <span className="text-[9px] text-[var(--color-muted)]">
              CPU utilization
            </span>
            <strong className="col-start-2 text-xl font-bold text-[var(--color-foreground)]">
              {data.cpu.utilization_percent.toFixed(1)}%
            </strong>
            <small className="col-span-2 truncate text-[8px] text-[var(--color-muted)]">
              {data.cpu.processor_name || "Processor name unavailable"} ·{" "}
              {data.cpu.logical_processors} logical
              {data.cpu.physical_cores
                ? ` · ${data.cpu.physical_cores} cores`
                : ""}
            </small>
          </div>
          <div className="grid grid-cols-[20px_1fr] items-center gap-x-2 gap-y-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-subtle)] p-3">
            <MemoryStick
              size={16}
              className="row-span-2 text-[var(--color-success)]"
            />
            <span className="text-[9px] text-[var(--color-muted)]">
              Memory utilization
            </span>
            <strong className="col-start-2 text-xl font-bold text-[var(--color-foreground)]">
              {data.memory.utilization_percent.toFixed(1)}%
            </strong>
            <small className="col-span-2 truncate text-[8px] text-[var(--color-muted)]">
              {formatBytes(data.memory.used_bytes)} used of{" "}
              {formatBytes(data.memory.total_bytes)}
            </small>
          </div>
          <div className="grid grid-cols-[20px_1fr] items-center gap-x-2 gap-y-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-subtle)] p-3">
            <HardDrive
              size={16}
              className="row-span-2 text-[var(--color-warning)]"
            />
            <span className="text-[9px] text-[var(--color-muted)]">
              Disk utilization
            </span>
            <strong className="col-start-2 text-xl font-bold text-[var(--color-foreground)]">
              {diskPercent === null
                ? "Unavailable"
                : `${diskPercent.toFixed(1)}%`}
            </strong>
            <small className="col-span-2 truncate text-[8px] text-[var(--color-muted)]">
              {data.storage_partitions.length} mounted volume
              {data.storage_partitions.length === 1 ? "" : "s"}
            </small>
          </div>
        </div>
        {history.isError && <QueryError error={history.error} />}
        <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
          <MetricChart
            title="CPU"
            color="#4a83d4"
            values={samples.map((item) => item.cpu_percent)}
          />
          <MetricChart
            title="Memory"
            color="#20a078"
            values={samples.map((item) => item.memory_percent)}
          />
          <MetricChart
            title="Disk"
            color="#c28b26"
            values={samples.flatMap((item) =>
              item.disk_percent === null ? [] : [item.disk_percent],
            )}
          />
        </div>
      </Panel>
      <div className="grid gap-4">
        <Panel>
          <PanelTitle>Storage volumes</PanelTitle>
          {data.storage_partitions.length ? (
            <div className="mt-2.5 grid gap-2">
              {data.storage_partitions.map((part, index) => (
                <div
                  className="grid grid-cols-[1fr_auto] gap-x-2 gap-y-1.5 rounded-lg border border-[var(--color-border)] p-2.5"
                  key={`${part.mountpoint}-${index}`}
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <strong className="truncate text-[9px] text-[var(--color-foreground)]">
                      {part.mountpoint || part.device || "Volume"}
                    </strong>
                    <span className="text-[8px] text-[var(--color-muted)]">
                      {part.filesystem || "Filesystem unavailable"}
                    </span>
                  </div>
                  <strong className="text-[9px] text-[var(--color-primary)]">
                    {part.utilization_percent.toFixed(1)}%
                  </strong>
                  <div className="col-span-2 h-1.5 overflow-hidden rounded-full bg-[var(--color-border)]">
                    <i
                      className="block h-full rounded-full bg-[var(--color-primary)]"
                      style={{
                        width: `${Math.min(100, part.utilization_percent)}%`,
                      }}
                    />
                  </div>
                  <small className="col-span-2 text-[8px] text-[var(--color-muted)]">
                    {formatBytes(part.used_bytes)} used ·{" "}
                    {formatBytes(part.free_bytes)} free of{" "}
                    {formatBytes(part.total_bytes)}
                  </small>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[9px] text-[var(--color-muted)]">
              Storage details unavailable.
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
