import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Monitor, Search, SlidersHorizontal } from "lucide-react";
import { devicesApi } from "./api";
import {
  PageHeader,
  Panel,
  QueryError,
  Skeleton,
  StatusBadge,
  Empty,
} from "../../components/ui";
import { Link } from "react-router-dom";

export function DevicesPage() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const statuses = useQuery({
    queryKey: ["statuses", devices.data?.map((d) => d.id)],
    queryFn: () => devicesApi.statuses(devices.data ?? []),
    enabled: !!devices.data,
    refetchInterval: false,
  });
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("search") ?? "");
  const [filter, setFilter] = useState("ALL");
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const filtered = useMemo(
    () =>
      (devices.data ?? []).filter((d) => {
        const status =
          statuses.data?.find((s) => s?.device_id === d.id)?.agent_state ??
          "UNKNOWN";
        const text =
          `${d.assigned_name ?? ""} ${d.hostname} ${d.id}`.toLowerCase();
        return (
          text.includes(search.toLowerCase()) &&
          (filter === "ALL" || status === filter)
        );
      }),
    [devices.data, statuses.data, search, filter],
  );
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize);
  return (
    <>
      <PageHeader
        eyebrow="FLEET MANAGEMENT"
        title="Devices"
        description="Browse registered endpoints and their latest server-reported status."
        action={
          <span className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[10px] text-[var(--color-muted)]">
            <Monitor size={15} />
            {devices.data?.length ?? 0} devices
          </span>
        }
      />
      {devices.isError && <QueryError error={devices.error} />}
      {statuses.isError && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[11px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          Some status requests failed. Affected devices show UNKNOWN.
        </div>
      )}
      <Panel>
        <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] p-4 max-[680px]:flex-col max-[680px]:items-stretch">
          <label className="flex h-9 w-[min(365px,65%)] items-center gap-2 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface-subtle)] px-2.5 text-[var(--color-muted)] max-[680px]:w-full">
            <Search size={17} />
            <input
              className="w-full border-0 bg-transparent text-[10px] text-[var(--color-foreground)] outline-none placeholder:text-[var(--color-muted)]"
              placeholder="Search name, hostname, or UUID…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setParams(e.target.value ? { search: e.target.value } : {});
                setPage(1);
              }}
            />
          </label>
          <label className="flex h-9 w-fit items-center gap-2 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface-subtle)] px-2.5 text-[var(--color-muted)]">
            <SlidersHorizontal size={16} />
            <select
              className="border-0 bg-transparent text-[10px] text-[var(--color-foreground)] outline-none"
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setPage(1);
              }}
            >
              <option value="ALL">All statuses</option>
              <option>ONLINE</option>
              <option>DELAYED</option>
              <option>OFFLINE</option>
              <option>NEVER_CONNECTED</option>
              <option>UNKNOWN</option>
            </select>
          </label>
        </div>
        {devices.isLoading ? (
          <Skeleton rows={7} />
        ) : rows.length ? (
          <div className="overflow-auto">
            <table className="w-full min-w-[880px] border-collapse whitespace-nowrap">
              <thead>
                <tr>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Device
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Hostname
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Device UUID
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Status
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Connection
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Last seen
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]">
                    Agent
                  </th>
                  <th className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((device) => {
                  const status = statuses.data?.find(
                    (s) => s?.device_id === device.id,
                  );
                  return (
                    <tr
                      className="group hover:bg-[var(--color-surface-subtle)]"
                      key={device.id}
                    >
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                        <Link
                          className="flex items-center gap-2"
                          to={`/devices/${device.id}`}
                        >
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
                            <Monitor size={16} />
                          </span>
                          <span>
                            <strong className="block text-[10px] text-[var(--color-foreground)]">
                              {device.assigned_name || device.hostname}
                            </strong>
                            <small className="mt-0.5 block text-[8px] text-[var(--color-muted)]">
                              {device.enrollment_state}
                            </small>
                          </span>
                        </Link>
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                        {device.hostname}
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 font-mono text-[9px] text-[var(--color-muted)]">
                        {device.id}
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                        <StatusBadge value={status?.agent_state ?? "UNKNOWN"} />
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                        {status
                          ? status.connected
                            ? "Connected"
                            : "Disconnected"
                          : "—"}
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                        {status?.last_seen_at
                          ? new Date(status.last_seen_at).toLocaleString()
                          : "—"}
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                        {device.agent_version ?? "—"}
                      </td>
                      <td className="border-b border-[var(--color-border)] px-3 py-3 text-right">
                        <Link
                          className="text-lg text-[var(--color-primary)] opacity-70 hover:opacity-100"
                          to={`/devices/${device.id}`}
                          aria-label="View details"
                        >
                          →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={
              search || filter !== "ALL"
                ? "No matching devices"
                : "No devices registered"
            }
            detail={
              search || filter !== "ALL"
                ? "Try changing your search or status filter."
                : "Approved devices will appear here when the server has registered them."
            }
          />
        )}
        {!!filtered.length && (
          <div className="flex items-center justify-between gap-3 border-t border-[var(--color-border)] px-4 py-3 text-[9px] text-[var(--color-muted)] max-[680px]:flex-col max-[680px]:items-start">
            <span>
              Showing {Math.min((page - 1) * pageSize + 1, filtered.length)}–
              {Math.min(page * pageSize, filtered.length)} of {filtered.length}
            </span>
            <div className="flex gap-1.5">
              <button
                className="rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 py-1 text-[9px] text-[var(--color-muted)] disabled:cursor-not-allowed disabled:opacity-45"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <button
                className="rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 py-1 text-[9px] text-[var(--color-muted)] disabled:cursor-not-allowed disabled:opacity-45"
                disabled={page * pageSize >= filtered.length}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Panel>
    </>
  );
}
