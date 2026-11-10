import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Panel, PanelTitle, QueryError, Skeleton } from "../../components/ui";
import { networkApi } from "./api";

export function DeviceNetworkEvents({ deviceId }: { deviceId: string }) {
  const [showFullInfo, setShowFullInfo] = useState(false);
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["network-events", showFullInfo, offset, deviceId],
    queryFn: () => networkApi.events(showFullInfo, offset, deviceId),
    refetchInterval: 15_000,
  });
  const monitoring = query.data?.monitoring.find((state) => state.device_id === deviceId);

  return (
    <Panel>
      <PanelTitle aside={<label className="flex items-center gap-2 text-[9px] text-[var(--color-muted)]">
        <input type="checkbox" checked={showFullInfo} onChange={(event) => { setOffset(0); setShowFullInfo(event.target.checked); }} />
        Show Full Info
      </label>}>
        Requests in the last 2 minutes
      </PanelTitle>
      <p className="my-3 text-[9px] text-[var(--color-muted)]">
        Windows Filtering Platform connection events for this device, refreshed every 15 seconds. These include permitted and blocked connection attempts, not packet contents.
      </p>
      {query.isError && <QueryError error={query.error} />}
      {monitoring ? (
        <div className={`mb-3 rounded border p-2 text-[9px] ${monitoring.status === "ACTIVE" && !monitoring.stale ? "border-emerald-500/40" : "border-amber-500/50"}`}>
          Monitoring: {monitoring.stale ? "STALE" : monitoring.status}
          {monitoring.gap_reason ? ` · ${monitoring.gap_reason}` : ""}
          {monitoring.error_code ? ` · ${monitoring.error_code}` : ""}
        </div>
      ) : query.data ? (
        <div className="mb-3 rounded border border-amber-500/50 p-2 text-[9px] text-[var(--color-muted)]">
          No WFP monitoring status is reported for this device. Check that its agent is updated and Windows connection auditing is enabled.
        </div>
      ) : null}
      {query.isLoading ? <Skeleton rows={4} /> : query.data?.events.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[950px] text-left text-[10px]">
            <thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
              <th className="p-2">Result</th><th className="p-2">Remote IP</th><th className="p-2">Process / PID</th>
              <th className="p-2">Protocol</th><th className="p-2">Endpoint</th><th className="p-2">Timestamp</th>
            </tr></thead>
            <tbody>{query.data.events.map((event) => (
              <tr key={event.id} className="border-b border-[var(--color-border)] last:border-0">
                <td className="p-2">{event.event_kind.replaceAll("_", " ").toLowerCase()}</td>
                <td className="p-2 font-mono">{event.remote_ip}<span className="block font-sans text-[8px] text-[var(--color-muted)]">{event.organization?.as_name ?? ""}</span></td>
                <td className="p-2">{event.process_path ?? "Unknown"}<span className="block text-[8px] text-[var(--color-muted)]">PID {event.process_id ?? "—"}</span></td>
                <td className="p-2">{event.protocol} · {event.direction.toLowerCase()}</td>
                <td className="p-2 font-mono">{showFullInfo
                  ? `${event.source_ip}:${event.source_port ?? "—"} → ${event.destination_ip}:${event.destination_port ?? "—"}`
                  : `${event.remote_ip}:${event.direction === "INCOMING" ? event.source_port ?? "—" : event.destination_port ?? "—"}`}</td>
                <td className="whitespace-nowrap p-2">{new Date(event.event_time).toLocaleString()}</td>
              </tr>
            ))}</tbody>
          </table>
          <div className="mt-3 flex items-center justify-between text-[8px] text-[var(--color-muted)]">
            <span>Showing {query.data.events.length} of {query.data.total} events. WFP history is separate from periodic socket snapshots.</span>
            <span className="flex gap-2">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</button>
              <button disabled={offset + 100 >= query.data.total} onClick={() => setOffset(offset + 100)}>Next</button>
            </span>
          </div>
        </div>
      ) : query.data ? (
        <p className="py-7 text-center text-[10px] text-[var(--color-muted)]">No matching WFP events in the last two minutes. Check this device’s monitoring status above.</p>
      ) : null}
    </Panel>
  );
}
