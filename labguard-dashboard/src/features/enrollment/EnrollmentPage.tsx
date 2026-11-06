import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clipboard, KeyRound, ShieldAlert, X } from "lucide-react";
import { enrollmentApi } from "./api";
import {
  Button,
  Empty,
  PageHeader,
  Panel,
  PanelTitle,
  QueryError,
  Skeleton,
  StatusBadge,
} from "../../components/ui";
import { canManageLabs } from "../auth/api";
import { useAuth } from "../auth/AuthProvider";
import { useToast } from "../../components/Toast";

export function EnrollmentPage() {
  const { admin } = useAuth();
  const toast = useToast();
  const allowed = canManageLabs(admin?.role);
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["enrollment"],
    queryFn: enrollmentApi.pending,
  });
  const [confirm, setConfirm] = useState<{
    id: string;
    name: string;
    action: "approve" | "reject";
  } | null>(null);
  const [assigned, setAssigned] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [copied, setCopied] = useState(false);
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["enrollment"] }),
      qc.invalidateQueries({ queryKey: ["devices"] }),
    ]);
  const decide = useMutation({
    mutationFn: () =>
      confirm?.action === "approve"
        ? enrollmentApi.approve(confirm.id, assigned)
        : enrollmentApi.reject(confirm!.id),
    onSuccess: async () => {
      const text =
        confirm?.action === "approve"
          ? "Device approved."
          : "Enrollment request rejected.";
      setMessage(text);
      toast(text);
      setConfirm(null);
      setAssigned("");
      await refresh();
    },
    onError: (e: Error) => {
      setMessage(e.message);
      toast(e.message, "error");
    },
  });
  const makeCode = useMutation({
    mutationFn: enrollmentApi.createCode,
    onSuccess: (result) => {
      setCode(result.code);
      setMessage(
        "Enrollment code created. Copy it now; the server only reveals it once.",
      );
    },
    onError: (e: Error) => {
      setMessage(e.message);
      toast(e.message, "error");
    },
  });
  return (
    <>
      <PageHeader
        eyebrow="DEVICE ONBOARDING"
        title="Enrollment requests"
        description="Review devices awaiting explicit administrator approval."
        action={
          allowed && (
            <Button
              className="bg-[var(--color-primary)] text-white"
              disabled={makeCode.isPending}
              onClick={() => makeCode.mutate()}
            >
              <KeyRound size={16} /> Generate code
            </Button>
          )
        }
      />
      {query.isError && <QueryError error={query.error} />}
      {message && (
        <div
          className={`relative mb-3.5 rounded-lg border px-3 py-2.5 text-[11px] ${decide.isError || makeCode.isError ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300" : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300"}`}
        >
          {message}
          <button
            className="absolute right-2 top-1 border-0 bg-transparent text-lg text-inherit"
            onClick={() => setMessage("")}
          >
            ×
          </button>
        </div>
      )}
      {code && (
        <Panel className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
            <KeyRound size={19} />
          </div>
          <div className="min-w-0 flex-1">
            <strong className="block text-xs text-[var(--color-foreground)]">
              One-time enrollment code
            </strong>
            <p className="font-mono text-sm text-[var(--color-foreground)]">
              {code}
            </p>
            <small className="text-[9px] text-[var(--color-muted)]">
              This secret is displayed once. Share it securely with the device
              operator.
            </small>
          </div>
          <Button
            onClick={async () => {
              await navigator.clipboard.writeText(code);
              setCopied(true);
            }}
          >
            <Clipboard size={15} />
            {copied ? "Copied" : "Copy"}
          </Button>
          <button
            className="grid h-8 w-8 place-items-center border-0 bg-transparent text-[var(--color-muted)]"
            onClick={() => setCode(null)}
            aria-label="Hide code"
          >
            <X size={17} />
          </button>
        </Panel>
      )}
      <Panel>
        <PanelTitle
          aside={
            <span className="rounded-full bg-[var(--color-primary-soft)] px-2 py-1 text-[9px] text-[var(--color-primary)]">
              {query.data?.length ?? 0} pending
            </span>
          }
        >
          Pending devices
        </PanelTitle>
        {query.isLoading ? (
          <Skeleton rows={4} />
        ) : query.data?.length ? (
          <div className="overflow-auto">
            <table className="w-full min-w-[700px] border-collapse whitespace-nowrap">
              <thead>
                <tr>
                  {[
                    "Device UUID",
                    "Hostname",
                    "Agent version",
                    "Request state",
                    "Actions",
                  ].map((label) => (
                    <th
                      className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-3 py-3 text-left text-[9px] font-semibold text-[var(--color-muted)]"
                      key={label}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {query.data.map((device) => (
                  <tr
                    className="hover:bg-[var(--color-surface-subtle)]"
                    key={device.id}
                  >
                    <td className="border-b border-[var(--color-border)] px-3 py-3 font-mono text-[9px] text-[var(--color-muted)]">
                      {device.id}
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-foreground)]">
                      <strong>{device.hostname}</strong>
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3 text-[10px] text-[var(--color-muted)]">
                      {device.agent_version ?? "—"}
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3">
                      <StatusBadge value="PENDING" />
                    </td>
                    <td className="border-b border-[var(--color-border)] px-3 py-3">
                      {allowed ? (
                        <div className="flex gap-2">
                          <Button
                            className="border-emerald-200 bg-emerald-50 text-emerald-700"
                            onClick={() => {
                              setConfirm({
                                id: device.id,
                                name: device.hostname,
                                action: "approve",
                              });
                              setAssigned(device.hostname);
                            }}
                          >
                            <Check size={14} /> Approve
                          </Button>
                          <Button
                            className="border-red-200 text-red-700"
                            onClick={() =>
                              setConfirm({
                                id: device.id,
                                name: device.hostname,
                                action: "reject",
                              })
                            }
                          >
                            <X size={14} /> Reject
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-[var(--color-muted)]">
                          Lab Admin required
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="All caught up"
            detail="There are no devices waiting for enrollment review."
          />
        )}
      </Panel>
      {confirm && (
        <div
          className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/40 p-4"
          role="presentation"
        >
          <section
            className="w-full max-w-[440px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <span
              className={`mb-3 grid h-10 w-10 place-items-center rounded-xl ${confirm.action === "reject" ? "bg-[var(--color-danger-soft)] text-[var(--color-danger)]" : "bg-[var(--color-warning-soft)] text-[var(--color-warning)]"}`}
            >
              <ShieldAlert size={21} />
            </span>
            <h2
              id="confirm-title"
              className="text-lg font-bold text-[var(--color-foreground)]"
            >
              {confirm.action === "approve"
                ? "Approve device?"
                : "Reject enrollment?"}
            </h2>
            <p className="my-3 text-sm leading-relaxed text-[var(--color-muted)]">
              {confirm.action === "approve"
                ? `Assign a name to ${confirm.name} before activating it.`
                : `Reject the pending enrollment from ${confirm.name}? This action cannot be undone.`}
            </p>
            {confirm.action === "approve" && (
              <label className="flex flex-col gap-1.5 text-xs font-semibold text-[var(--color-muted)]">
                Assigned device name
                <input
                  className="h-9 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 text-sm text-[var(--color-foreground)]"
                  autoFocus
                  value={assigned}
                  onChange={(e) => setAssigned(e.target.value)}
                  maxLength={100}
                />
              </label>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <Button onClick={() => setConfirm(null)}>Cancel</Button>
              <Button
                className={
                  confirm.action === "reject"
                    ? "bg-[var(--color-danger)] text-white"
                    : "bg-[var(--color-primary)] text-white"
                }
                disabled={
                  decide.isPending ||
                  (confirm.action === "approve" && !assigned.trim())
                }
                onClick={() => decide.mutate()}
              >
                {decide.isPending
                  ? "Saving…"
                  : confirm.action === "approve"
                    ? "Approve device"
                    : "Reject request"}
              </Button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
