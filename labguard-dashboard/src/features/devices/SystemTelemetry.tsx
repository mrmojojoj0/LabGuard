import { useQuery } from "@tanstack/react-query";
import { Cpu, MemoryStick, HardDrive, Activity } from "lucide-react";
import { devicesApi } from "./api";
import { Panel, PanelTitle, QueryError, Skeleton } from "../../components/ui";
import type { TelemetrySample } from "../../lib/types";

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
  const os = data.operating_system;
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
      <div className="grid gap-4 min-[981px]:grid-cols-2">
        <Panel>
          <PanelTitle>Operating system & uptime</PanelTitle>
          <div className="grid">
            {(
              [
                ["Windows edition", os.edition || "Unavailable"],
                ["Version", os.version || "Unavailable"],
                ["Build", os.build_number || "Unavailable"],
                ["Architecture", os.architecture || "Unavailable"],
                ["Hostname", os.hostname || "Unavailable"],
                ["Uptime", formatUptime(data.uptime_seconds)],
                ["Boot time", new Date(data.boot_time).toLocaleString()],
              ] as Array<[string, string]>
            ).map(([label, value], index, values) => (
              <div
                className={`flex justify-between gap-3 py-2.5 text-[10px] ${index < values.length - 1 ? "border-b border-[var(--color-border)]" : ""}`}
                key={label}
              >
                <span className="text-[var(--color-muted)]">{label}</span>
                <strong className="text-right text-[var(--color-foreground)]">
                  {value}
                </strong>
              </div>
            ))}
          </div>
        </Panel>
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
      <Panel>
        <PanelTitle>Network interfaces</PanelTitle>
        {data.network_interfaces.length ? (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {data.network_interfaces.map((item, index) => (
              <div
                className="flex flex-col gap-1.5 rounded-lg border border-[var(--color-border)] p-2.5"
                key={`${item.name}-${index}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-[9px] text-[var(--color-foreground)]">
                    {item.name}
                  </strong>
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[7px] font-bold ${item.status.toLowerCase() === "up" ? "bg-[var(--color-success-soft)] text-[var(--color-success)]" : item.status.toLowerCase() === "down" ? "bg-[var(--color-danger-soft)] text-[var(--color-danger)]" : "bg-[var(--color-surface-subtle)] text-[var(--color-muted)]"}`}
                  >
                    {item.status}
                  </span>
                </div>
                <small className="text-[8px] text-[var(--color-muted)]">
                  MAC {item.mac_address || "Unavailable"}
                  {item.speed_mbps
                    ? ` · ${item.speed_mbps.toLocaleString()} Mbps`
                    : ""}
                </small>
                <small className="text-[8px] text-[var(--color-muted)]">
                  IPv4 {item.ipv4_addresses.join(", ") || "Unavailable"}
                </small>
                <small className="text-[8px] text-[var(--color-muted)]">
                  IPv6 {item.ipv6_addresses.join(", ") || "Unavailable"}
                </small>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[9px] text-[var(--color-muted)]">
            Network interface details unavailable.
          </div>
        )}
      </Panel>
    </div>
  );
}
