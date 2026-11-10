import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button, Loading, Panel, PanelTitle, QueryError } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { devicesApi } from "./api";
import type { DeviceProcessEntry } from "../../lib/types";

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  do { value /= 1024; unit += 1; } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(1)} ${units[unit]}`;
}

function processResultMessage(code: string | null): string {
  const messages: Record<string, string> = {
    terminated: "Process termination completed.",
    killed: "Force kill completed.",
    process_not_found: "That process has already exited.",
    pid_reused: "The PID now belongs to a different process. Nothing was terminated.",
    access_denied: "Windows denied access to that process.",
    invalid_process_identity: "That process is protected from termination.",
    protected_process: "Windows system processes are protected from termination.",
    terminate_timeout: "The process did not exit before the timeout.",
    kill_timeout: "The process did not exit before the timeout.",
    operation_failed: "Windows could not complete the process operation.",
    process_list_truncated: "Process list reached its 1,000 entry limit.",
    process_list_failed: "The endpoint could not collect the process list.",
    agent_unavailable: "The endpoint disconnected before it handled the request.",
    request_expired: "The request expired before the endpoint completed it.",
    invalid_process_list: "The endpoint returned an invalid process list.",
  };
  return code ? messages[code] ?? `Process operation returned ${code}.` : "Process request completed.";
}

export function DeviceProcesses({ deviceId }: { deviceId: string }) {
  const toast = useToast();
  const [listRequestId, setListRequestId] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"name" | "pid" | "cpu" | "memory" | "username">("name");
  const [descending, setDescending] = useState(false);
  const [groupSimilar, setGroupSimilar] = useState(true);
  const [hideSystemProcesses, setHideSystemProcesses] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
  const groupQueue = useRef<DeviceProcessEntry[]>([]);
  const groupKillState = useRef<{ active: boolean; total: number; completed: number; succeeded: number }>({ active: false, total: 0, completed: 0, succeeded: 0 });
  const handledActionId = useRef<string | null>(null);
  const autoRequestedFor = useRef<string | null>(null);
  const listMutation = useMutation({
    mutationFn: () => devicesApi.requestProcessOperation(deviceId, "LIST"),
    onSuccess: (request) => setListRequestId(request.id),
    onError: (error: Error) => toast(`Could not request process list. ${error.message}`, "error"),
  });
  const actionMutation = useMutation({
    mutationFn: ({ operation, process }: { operation: "TERMINATE" | "KILL"; process: DeviceProcessEntry }) =>
      devicesApi.requestProcessOperation(deviceId, operation, {
        target_pid: process.pid,
        target_created_at_us: process.created_at_us!,
      }),
    onSuccess: (request) => setActionRequestId(request.id),
    onError: (error: Error) => {
      groupQueue.current = [];
      groupKillState.current.active = false;
      toast(`Process request failed. ${error.message}`, "error");
    },
  });
  useEffect(() => {
    if (autoRequestedFor.current === deviceId) return;
    autoRequestedFor.current = deviceId;
    listMutation.mutate();
  }, [deviceId, listMutation.mutate]);
  const processList = useQuery({
    queryKey: ["device-process-request", deviceId, listRequestId],
    queryFn: () => devicesApi.processRequest(deviceId, listRequestId!),
    enabled: Boolean(listRequestId),
    refetchInterval: (query) => query.state.data?.status === "PENDING" ? 750 : false,
    retry: false,
  });
  const processAction = useQuery({
    queryKey: ["device-process-request", deviceId, actionRequestId],
    queryFn: () => devicesApi.processRequest(deviceId, actionRequestId!),
    enabled: Boolean(actionRequestId),
    refetchInterval: (query) => query.state.data?.status === "PENDING" ? 750 : false,
    retry: false,
  });

  useEffect(() => {
    const result = processAction.data;
    if (!result || result.status === "PENDING" || handledActionId.current === result.id) return;
    handledActionId.current = result.id;
    const successful = result.result_code === "terminated" || result.result_code === "killed";
    if (groupKillState.current.active) {
      groupKillState.current.completed += 1;
      if (successful) groupKillState.current.succeeded += 1;
    } else {
      toast(processResultMessage(result.result_code), successful ? "success" : "error");
    }
    const next = groupQueue.current.shift();
    if (next) actionMutation.mutate({ operation: "KILL", process: next });
    else {
      if (groupKillState.current.active) {
        const { total, completed, succeeded } = groupKillState.current;
        groupKillState.current.active = false;
        toast(`Force kill group finished: ${succeeded} of ${completed} process(es) stopped.`, succeeded === total ? "success" : "error");
      }
      if (result.status !== "EXPIRED") listMutation.mutate();
    }
  }, [processAction.data, actionMutation, listMutation, toast]);

  const rows = processList.data?.status === "COMPLETE"
    ? (processList.data.processes ?? []).filter((process) =>
      process.pid !== 0 && process.name.toLocaleLowerCase() !== "system idle process" &&
      !(hideSystemProcesses && process.username?.trim().toLocaleLowerCase().startsWith("nt authority\\")))
    : [];
  const actionBusy = actionMutation.isPending || processAction.data?.status === "PENDING";
  const requestStatus = processList.data?.status;

  const groups = useMemo(() => {
    const grouped = new Map<string, DeviceProcessEntry[]>();
    for (const process of rows) {
      const executable = process.executable_path?.split(/[\\/]/).pop() || process.name;
      const key = executable.trim().toLocaleLowerCase();
      grouped.set(key, [...(grouped.get(key) ?? []), process]);
    }
    const compareValues = (a: DeviceProcessEntry, b: DeviceProcessEntry) => {
      let result = 0;
      if (sortBy === "pid") result = a.pid - b.pid;
      else if (sortBy === "cpu") result = (a.cpu_percent ?? -1) - (b.cpu_percent ?? -1);
      else if (sortBy === "memory") result = (a.memory_bytes ?? -1) - (b.memory_bytes ?? -1);
      else if (sortBy === "username") result = (a.username ?? "").localeCompare(b.username ?? "");
      else result = a.name.localeCompare(b.name);
      return descending ? -result : result;
    };
    const result = [...grouped.entries()].map(([key, processes]) => ({
      key,
      processes: [...processes].sort(compareValues),
    }));
    result.sort((a, b) => compareValues(a.processes[0], b.processes[0]));
    return result;
  }, [rows, sortBy, descending]);

  const runAction = (operation: "TERMINATE" | "KILL", process: DeviceProcessEntry) => {
    if (process.created_at_us === null) return;
    const verb = operation === "KILL" ? "Force kill" : "Terminate";
    if (!window.confirm(`${verb} ${process.name} (PID ${process.pid})? Windows may close it immediately without saving.`)) return;
    actionMutation.mutate({ operation, process });
  };

  const runGroupKill = (processes: DeviceProcessEntry[]) => {
    const eligible = processes.filter((process) => process.created_at_us !== null && process.pid !== 0 && process.pid !== 4);
    if (!eligible.length) return;
    const name = eligible[0].name;
    if (!window.confirm(`Force kill all ${eligible.length} instance(s) of ${name}? Each process will be checked by PID and creation time. Windows may close them immediately without saving.`)) return;
    groupKillState.current = { active: true, total: eligible.length, completed: 0, succeeded: 0 };
    groupQueue.current = eligible.slice(1);
    actionMutation.mutate({ operation: "KILL", process: eligible[0] });
  };

  return <Panel>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <PanelTitle>Processes</PanelTitle>
      <Button disabled={listMutation.isPending || requestStatus === "PENDING" || actionBusy} onClick={() => listMutation.mutate()}>
        {listMutation.isPending || requestStatus === "PENDING" ? "Refreshing…" : "Refresh process list"}
      </Button>
    </div>
    <p className="my-2 text-[10px] leading-relaxed text-[var(--color-muted)]">
      Process details include usernames and executable paths and are visible to lab admins. Terminate uses the Windows process API; on Windows it can end a process immediately without a save prompt. Force Kill uses the same Windows termination mechanism and is provided as a separate explicit action. Each action checks both PID and process creation time to avoid PID reuse.
    </p>
    {processList.isError && <QueryError error={processList.error} />}
    {processAction.isError && <QueryError error={processAction.error} />}
    {processList.data?.status === "FAILED" && <p role="alert" className="mb-2 text-[10px] text-red-700">{processResultMessage(processList.data.result_code)}</p>}
    {processList.data?.status === "EXPIRED" && <p role="alert" className="mb-2 rounded border border-amber-500/50 bg-amber-500/5 p-3 text-[10px] text-amber-800 dark:text-amber-200">The process request timed out without a response. Confirm the LabGuard Agent is updated, running, and connected, then refresh the process list.</p>}
    {requestStatus === "PENDING" && <Loading label="Collecting process details…" />}
    {requestStatus === "COMPLETE" && processList.data?.result_code === "process_list_truncated" &&
      <p className="mb-2 text-[10px] text-amber-700">{processResultMessage(processList.data.result_code)}</p>}
    {rows.length > 0 && <div className="mb-3 flex flex-wrap items-center gap-3 text-[9px]">
      <label className="flex items-center gap-1.5 text-[var(--color-muted)]">
        Sort by
        <select className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-1 text-[var(--color-foreground)]" value={sortBy} onChange={(event) => setSortBy(event.target.value as typeof sortBy)}>
          <option value="name">Executable</option><option value="pid">PID</option><option value="cpu">CPU</option><option value="memory">Memory</option><option value="username">Username</option>
        </select>
      </label>
      <button className="text-[var(--color-primary)]" onClick={() => setDescending((value) => !value)}>{descending ? "Descending ↓" : "Ascending ↑"}</button>
      <label className="flex items-center gap-1.5 text-[var(--color-muted)]"><input type="checkbox" checked={groupSimilar} onChange={(event) => setGroupSimilar(event.target.checked)} />Group similar executables</label>
      <label className="flex items-center gap-1.5 text-[var(--color-muted)]"><input type="checkbox" checked={hideSystemProcesses} onChange={(event) => setHideSystemProcesses(event.target.checked)} />Hide NT AUTHORITY processes</label>
    </div>}
    {rows.length > 0 && <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-left text-[10px]">
        <thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
          <th className="p-2">PID</th><th className="p-2">Name</th><th className="p-2">Username</th>
          <th className="p-2">CPU</th><th className="p-2">Memory</th><th className="p-2">Executable path</th>
          <th className="p-2">Actions</th>
        </tr></thead>
        <tbody>{groups.flatMap((group) => {
          const expanded = expandedGroups.has(group.key);
          const cpuValues = group.processes.map((process) => process.cpu_percent).filter((value): value is number => value !== null);
          const memoryValues = group.processes.map((process) => process.memory_bytes).filter((value): value is number => value !== null);
          const users = [...new Set(group.processes.map((process) => process.username).filter((value): value is string => Boolean(value)))];
          const paths = [...new Set(group.processes.map((process) => process.executable_path).filter((value): value is string => Boolean(value)))];
          const totalCpu = cpuValues.reduce((total, value) => total + value, 0);
          const totalMemory = memoryValues.reduce((total, value) => total + value, 0);
          return [
          ...(groupSimilar ? [<tr key={`group:${group.key}`} className="border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)]">
            <td className="p-2 text-[var(--color-muted)]">{group.processes.length} process{group.processes.length === 1 ? "" : "es"}</td>
            <td className="max-w-[180px] p-2 font-semibold text-[var(--color-foreground)]">
              <button
                type="button"
                aria-label={`${expanded ? "Collapse" : "Show"} ${group.processes[0].name} processes`}
                aria-expanded={expanded}
                className="inline-flex items-center gap-1 text-left"
                onClick={() => setExpandedGroups((current) => {
                  const next = new Set(current);
                  if (next.has(group.key)) next.delete(group.key);
                  else next.add(group.key);
                  return next;
                })}
              >
                {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <span className="truncate" title={group.processes[0].name}>{group.processes[0].name}</span>
              </button>
            </td>
            <td className="p-2" title={users.join(", ")}>{users.length === 0 ? "—" : users.length === 1 ? users[0] : `${users.length} users`}</td>
            <td className="p-2">{cpuValues.length ? `${totalCpu.toFixed(1)}%` : "—"}</td>
            <td className="p-2">{memoryValues.length ? formatBytes(totalMemory) : "—"}</td>
            <td className="max-w-[320px] truncate p-2 font-mono" title={paths.length === 1 ? paths[0] : paths.length > 1 ? `${paths.length} executable paths` : ""}>
              {paths.length === 1 ? paths[0] : paths.length > 1 ? `${paths.length} executable paths` : "—"}
            </td>
            <td className="p-2">{group.processes.length > 1 && <Button disabled={actionBusy} onClick={() => runGroupKill(group.processes)}>Force kill all</Button>}</td>
          </tr>] : []),
          ...(groupSimilar && !expandedGroups.has(group.key) ? [] : group.processes).map((process) => <tr key={`${process.pid}:${process.created_at_us ?? "unknown"}`} className="border-b border-[var(--color-border)]">
          <td className="p-2 font-mono">{process.pid}</td>
          <td className="max-w-[180px] truncate p-2" title={process.name}>{process.name}</td>
          <td className="max-w-[180px] truncate p-2" title={process.username ?? ""}>{process.username ?? "—"}</td>
          <td className="p-2">{process.cpu_percent === null ? "—" : `${process.cpu_percent.toFixed(1)}%`}</td>
          <td className="p-2">{formatBytes(process.memory_bytes)}</td>
          <td className="max-w-[320px] truncate p-2 font-mono" title={process.executable_path ?? ""}>{process.executable_path ?? "—"}</td>
          <td className="p-2"><div className="flex gap-1">
            <Button disabled={actionBusy || process.created_at_us === null || process.pid === 0 || process.pid === 4} onClick={() => runAction("TERMINATE", process)}>Terminate</Button>
            <Button disabled={actionBusy || process.created_at_us === null || process.pid === 0 || process.pid === 4} onClick={() => runAction("KILL", process)}>Force Kill</Button>
          </div></td>
        </tr>),
        ];
        })}</tbody>
      </table>
    </div>}
    {requestStatus === "COMPLETE" && rows.length === 0 && <p className="p-4 text-center text-[10px] text-[var(--color-muted)]">No processes were returned.</p>}
    {!listRequestId && <p className="p-4 text-center text-[10px] text-[var(--color-muted)]">Refresh to view processes running on this device.</p>}
    {actionBusy && <div className="mt-2"><Loading label="Waiting for the endpoint process result…" /></div>}
  </Panel>;
}
