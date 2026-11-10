import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Globe2, Network } from "lucide-react";
import { PageHeader, Panel, PanelTitle, QueryError, Skeleton } from "../../components/ui";
import { networkApi } from "./api";

export function NetworkMonitoringPage() {
  const [showFullInfo, setShowFullInfo] = useState(false);
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["network-connections"],
    queryFn: networkApi.connections,
    refetchInterval: 30_000,
  });
  const eventQuery = useQuery({
    queryKey: ["network-events", showFullInfo, offset],
    queryFn: () => networkApi.events(showFullInfo, offset),
    refetchInterval: 15_000,
  });

  return (
    <>
      <PageHeader
        eyebrow="MONITORING"
        title="Network Monitoring"
        description="Historical Windows Filtering Platform events and periodic psutil socket snapshots."
      />
      {query.isError && <QueryError error={query.error} />}
      {query.isLoading ? <Skeleton rows={6} /> : query.data && (
        <div className="grid gap-4">
          {!query.data.lookups_enabled && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-[10px] text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
              IP ownership lookup is not configured. Set <code>IPINFO_TOKEN</code> in the server's environment and restart it to show ASN organizations.
            </div>
          )}
          <Panel>
            <PanelTitle aside={<div className="flex items-center gap-3 text-[9px] text-[var(--color-muted)]">
              <label className="flex items-center gap-2"><input type="checkbox" checked={showFullInfo} onChange={(event) => { setOffset(0); setShowFullInfo(event.target.checked); }} />Show Full Info</label>
              <span>{query.data.public_ip_count} public IPs</span>
            </div>}>
              Active socket snapshots · public IPs
            </PanelTitle>
            <p className="my-3 text-[9px] leading-relaxed text-[var(--color-muted)]">
              Source: periodic psutil snapshots, refreshed with device telemetry about every 30 seconds. Only globally routable remote IP addresses are sent to IPinfo. Private/local addresses are excluded; the organization shown is the ASN network operator and may not be the specific owner of a server or service.
            </p>
            {query.data.connections.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[850px] text-left text-[10px]">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
                      <th className="p-2">Device</th>
                      <th className="p-2">Public IP</th>
                      <th className="p-2">Network operator</th>
                      <th className="p-2">Country</th>
                      <th className="p-2">Connection</th>
                      {showFullInfo && <><th className="p-2">Local port</th><th className="p-2">Interface / state</th></>}
                      <th className="p-2">Observed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.connections.map((connection, index) => (
                      <tr className="border-b border-[var(--color-border)] last:border-0" key={[connection.device_id, connection.remote_ip, connection.remote_port, connection.local_port, index].join(":")}>
                        <td className="p-2 font-medium text-[var(--color-foreground)]">{connection.device_name}</td>
                        <td className="whitespace-nowrap p-2 font-mono">
                          <span className="inline-flex items-center gap-1"><Globe2 size={12} />{connection.remote_ip}{showFullInfo && connection.remote_port ? ":" + connection.remote_port : ""}</span>
                        </td>
                        <td className="p-2">
                          {connection.organization?.as_name ?? (query.data.lookups_enabled ? "Lookup unavailable" : "Not configured")}
                          {connection.organization?.asn && <span className="block text-[8px] text-[var(--color-muted)]">{connection.organization.asn}{connection.organization.as_domain ? " · " + connection.organization.as_domain : ""}</span>}
                        </td>
                        <td className="p-2">{connection.organization?.country ?? "—"}</td>
                        <td className="whitespace-nowrap p-2">{connection.direction.toLowerCase()} · {connection.protocol}</td>
                        {showFullInfo && <><td className="p-2 font-mono">{connection.local_port}</td><td className="p-2">{connection.interface} · {connection.state}</td></>}
                        <td className="whitespace-nowrap p-2 text-[9px] text-[var(--color-muted)]">{connection.observed_at ? new Date(connection.observed_at).toLocaleString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="grid justify-items-center gap-2 py-9 text-center text-[10px] text-[var(--color-muted)]">
                <Network size={20} />
                No public-IP connections are currently reported.
              </div>
            )}
            <p className="mt-3 text-[8px] text-[var(--color-muted)]">Showing up to 200 active connections and looking up up to 40 distinct public IPs per refresh. IPinfo Lite provides ASN, organization name/domain, and country-level data.</p>
          </Panel>
          <Panel>
            <PanelTitle>
              Requests in the last 2 minutes
            </PanelTitle>
            <p className="my-3 text-[9px] text-[var(--color-muted)]">
              Rolling view of Windows Filtering Platform events, refreshed every 15 seconds. It includes permitted and blocked connection attempts; this is connection auditing, not packet contents, and domain names are not inferred from IP addresses.
            </p>
            {eventQuery.isError && <QueryError error={eventQuery.error} />}
            {!!eventQuery.data?.monitoring.length && (
              <div className="mb-3 flex flex-wrap gap-2">
                {eventQuery.data.monitoring.map((state) => (
                  <span key={state.device_id} className={`rounded border px-2 py-1 text-[9px] ${state.status === "ACTIVE" && !state.stale ? "border-emerald-500/40" : "border-amber-500/50"}`}>
                    {state.device_name}: {state.stale ? "STALE" : state.status}{state.gap_reason ? ` · ${state.gap_reason}` : ""}{state.error_code ? ` · ${state.error_code}` : ""}
                  </span>
                ))}
              </div>
            )}
            {eventQuery.data && eventQuery.data.monitoring.length === 0 && (
              <div className="mb-3 rounded border border-amber-500/50 p-2 text-[9px] text-[var(--color-muted)]">
                No WFP monitoring status has been reported by an agent yet. Confirm the client is updated and Windows connection auditing is enabled.
              </div>
            )}
            {eventQuery.isLoading ? <Skeleton rows={4} /> : eventQuery.data?.events.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1050px] text-left text-[10px]">
                  <thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
                    <th className="p-2">Device / source</th><th className="p-2">Result</th><th className="p-2">Remote IP</th>
                    <th className="p-2">Process</th><th className="p-2">Protocol</th><th className="p-2">Endpoints</th><th className="p-2">Timestamp</th>
                  </tr></thead>
                  <tbody>{eventQuery.data.events.map((event) => (
                    <tr key={event.id} className="border-b border-[var(--color-border)] last:border-0">
                      <td className="p-2">{event.device_name}<span className="block text-[8px] text-[var(--color-muted)]">Windows Filtering Platform · event {event.event_id}</span></td>
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
              </div>
            ) : <div className="py-8 text-center text-[10px] text-[var(--color-muted)]">No matching WFP events reported. Check each device’s monitoring state and Windows audit policy.</div>}
            {eventQuery.data && <div className="mt-3 flex items-center justify-between text-[8px] text-[var(--color-muted)]">
              <span>Showing {eventQuery.data.events.length} of {eventQuery.data.total} matching events. WFP events and psutil socket snapshots are separate sources.</span>
              <span className="flex gap-2"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</button>
                <button disabled={offset + 100 >= eventQuery.data.total} onClick={() => setOffset(offset + 100)}>Next</button></span>
            </div>}
          </Panel>
        </div>
      )}
    </>
  );
}
