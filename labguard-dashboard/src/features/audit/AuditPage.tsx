import { useQuery } from "@tanstack/react-query";
import { FileClock } from "lucide-react";
import { auditApi } from "./api";
import {
  Empty,
  PageHeader,
  Panel,
  QueryError,
  Skeleton,
  StatusBadge,
} from "../../components/ui";
export function AuditPage() {
  const query = useQuery({ queryKey: ["audit"], queryFn: auditApi.list });
  return (
    <>
      <PageHeader
        eyebrow="SECURITY & GOVERNANCE"
        title="Audit logs"
        description="Recent administrator actions recorded by the LabGuard server."
        action={
          <span className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[10px] text-[var(--color-muted)]">
            <FileClock size={15} />
            {query.data?.length ?? 0} events
          </span>
        }
      />
      {query.isError && <QueryError error={query.error} />}
      <Panel>
        {query.isLoading ? (
          <Skeleton rows={7} />
        ) : query.data?.length ? (
          <div className="overflow-auto">
            <table className="w-full min-w-[700px] border-collapse whitespace-nowrap">
              <thead>
                <tr>
                  {["Action", "Actor", "Target", "Result", "Time"].map(
                    (label) => (
                      <th
                        className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]"
                        key={label}
                      >
                        {label}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {query.data.map((e) => (
                  <tr
                    className="hover:bg-[var(--color-surface-subtle)]"
                    key={e.id}
                  >
                    <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] font-semibold capitalize text-[var(--color-foreground)]">
                      {e.action.replaceAll(".", " ")}
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                      {e.actor_type}
                      {e.actor_id ? ` · ${e.actor_id.slice(0, 8)}` : ""}
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                      {e.target_type}
                      {e.target_id ? ` · ${e.target_id.slice(0, 12)}` : ""}
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3">
                      <StatusBadge value={e.result} />
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                      {new Date(e.occurred_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="No audit events"
            detail="The server has not returned any audit records yet."
          />
        )}
      </Panel>
    </>
  );
}
