import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CalendarClock, Download, ShieldAlert, X } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Empty, PageHeader, Panel, PanelTitle, QueryError, Skeleton, StatusBadge } from "../../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { devicesApi } from "../devices/api";
import { roomsApi } from "../rooms/api";
import { examsApi, type ExamPolicy } from "./api";

const emptyPolicy: ExamPolicy = { network_mode: "MONITOR", allowed_networks: [], restricted_apps: [],
  restrict_browsers: false, restricted_browsers: [], block_usb_storage: false, screenshot_on_violation: true };
const localInputDate = (value: Date) => new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);

export function ExamsPage() {
  const { admin } = useAuth();
  const queryClient = useQueryClient();
  const exams = useQuery({ queryKey: ["exams"], queryFn: examsApi.list, refetchInterval: 5_000 });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: roomsApi.list });
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const [roomId, setRoomId] = useState("");
  const [title, setTitle] = useState("");
  const [startsAt, setStartsAt] = useState(() => localInputDate(new Date(Date.now() + 60_000)));
  const [endsAt, setEndsAt] = useState(() => localInputDate(new Date(Date.now() + 61 * 60_000)));
  const [policy, setPolicy] = useState<ExamPolicy>(emptyPolicy);
  const [appsText, setAppsText] = useState("");
  const [networksText, setNetworksText] = useState("");
  const [reportId, setReportId] = useState<string | null>(null);
  const [eventsDeviceId, setEventsDeviceId] = useState<string | null>(null);
  const [renameDeviceId, setRenameDeviceId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  useEffect(() => {
    if (!eventsDeviceId) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setEventsDeviceId(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [eventsDeviceId]);
  const selectedRoom = rooms.data?.find((room) => room.id === roomId);
  const layout = useQuery({ queryKey: ["room-layout", roomId], queryFn: () => roomsApi.layout(roomId), enabled: Boolean(roomId) });
  const assignedIds = useMemo(() => layout.data?.assignments.map((item) => item.device_id) ?? [], [layout.data]);
  const targetIds = assignedIds;
  const statuses = useQuery({ queryKey: ["exam-statuses", targetIds.join(",")],
    queryFn: async () => {
      const targets = (devices.data ?? []).filter((device) => targetIds.includes(device.id));
      const values = await devicesApi.statuses(targets);
      return Object.fromEntries(targets.map((device, index) => [device.id, values[index]]));
    },
    enabled: targetIds.length > 0, refetchInterval: 5_000 });
  const report = useQuery({ queryKey: ["exam-report", reportId], queryFn: () => examsApi.report(reportId!), enabled: Boolean(reportId) });
  const create = useMutation({ mutationFn: examsApi.create, onSuccess: () => {
    setTitle(""); void queryClient.invalidateQueries({ queryKey: ["exams"] });
  } });
  const cancel = useMutation({ mutationFn: examsApi.cancel, onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["exams"] }) });
  const rename = useMutation({ mutationFn: ({ id, name }: { id: string; name: string }) => devicesApi.rename(id, name),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["devices"] }),
        queryClient.invalidateQueries({ queryKey: ["exam-report", reportId] }),
      ]);
      setRenameDeviceId(null);
    },
  });
  const canManage = admin?.role === "LAB_ADMIN" || admin?.role === "SUPER_ADMIN";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!selectedRoom || !targetIds.length) return;
    const finalPolicy = { ...policy,
      allowed_networks: networksText.split(/[\s,;]+/).filter(Boolean),
      restricted_apps: appsText.split(/[\s,;]+/).filter(Boolean) };
    create.mutate({ title, room_id: selectedRoom.id, device_ids: targetIds,
      starts_at: new Date(startsAt).toISOString(), ends_at: new Date(endsAt).toISOString(), policy: finalPolicy });
  };

  return <div className="mx-auto max-w-6xl p-4 md:p-6">
    <PageHeader eyebrow="EXAM INTEGRITY" title="Exam management"
      description="Schedule exams against existing lab layouts, review agent health, and export an auditable report." />
    {create.error && <QueryError error={create.error} />}{exams.error && <QueryError error={exams.error} />}
    {canManage && <Panel className="mb-5"><PanelTitle>Create a scheduled exam</PanelTitle>
      <form onSubmit={submit} className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-[10px] font-semibold">Exam name<input required maxLength={160} value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2" /></label>
        <label className="text-[10px] font-semibold">Lab<select required value={roomId} onChange={(e) => setRoomId(e.target.value)} className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2"><option value="">Select a lab</option>{rooms.data?.map((room) => <option value={room.id} key={room.id}>{room.name}</option>)}</select></label>
        <label className="text-[10px] font-semibold">Starts (local time)<input type="datetime-local" required value={startsAt} onChange={(e) => setStartsAt(e.target.value)} className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2" /></label>
        <label className="text-[10px] font-semibold">Ends (local time)<input type="datetime-local" required value={endsAt} onChange={(e) => setEndsAt(e.target.value)} className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2" /></label>
        <div className="text-[10px] text-[var(--color-muted)] md:col-span-2">{layout.isLoading ? "Loading lab positions…" : "All PCs assigned to this lab are included."}</div>
        <div className="grid gap-3 rounded-lg border border-[var(--color-border)] p-3 md:col-span-2 md:grid-cols-2">
          <label className="flex items-center gap-2 text-[10px]"><input type="checkbox" checked={policy.network_mode === "ALLOW_LIST"} onChange={(e) => setPolicy({ ...policy, network_mode: e.target.checked ? "ALLOW_LIST" : "MONITOR" })} />Configure network allow-list policy</label>
          <label className="flex items-center gap-2 text-[10px]"><input type="checkbox" checked={policy.block_usb_storage} onChange={(e) => setPolicy({ ...policy, block_usb_storage: e.target.checked })} />Request USB storage restriction</label>
          <label className="flex items-center gap-2 text-[10px]"><input type="checkbox" checked={policy.restrict_browsers} onChange={(e) => setPolicy({ ...policy, restrict_browsers: e.target.checked })} />Restrict common browsers (Edge, Chrome, Firefox)</label>
          <p className="m-0 text-[10px] text-[var(--color-muted)]">Every exam violation queues four screenshots: immediately, then after 10, 20, and 30 seconds.</p>
          <label className="text-[10px]">Allowed IP/CIDR ranges<textarea disabled={policy.network_mode !== "ALLOW_LIST"} value={networksText} onChange={(e) => setNetworksText(e.target.value)} placeholder="10.0.0.0/8, 2001:db8::/32" className="mt-1 block min-h-16 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2" /></label>
          <label className="text-[10px] md:col-span-2">Restricted executable names<textarea value={appsText} onChange={(e) => setAppsText(e.target.value)} placeholder="game.exe, discord.exe" className="mt-1 block min-h-16 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2" /></label>
        </div>
        <div className="rounded-md bg-amber-50 p-2 text-[9px] text-amber-900 dark:bg-amber-950/30 dark:text-amber-200 md:col-span-2">Policies are recorded with the exam. Endpoint enforcement and automatic violation screenshots require a compatible updated agent; this dashboard reports that distinction and does not claim policy application.</div>
        <Button className="w-fit" disabled={!title.trim() || !roomId || !targetIds.length || create.isPending}>Schedule exam</Button>
      </form>
    </Panel>}

    <Panel className="mb-5"><PanelTitle aside={<span className="text-[9px] text-[var(--color-muted)]">Refreshes every 5 seconds</span>}>Scheduled exams and live PC status</PanelTitle>
      {exams.isLoading ? <Skeleton rows={3} /> : exams.data?.length ? <div className="mt-3 space-y-3">{exams.data.map((exam) => <ExamCard key={exam.id} exam={exam} onReport={() => setReportId(exam.id)} onCancel={() => cancel.mutate(exam.id)} canManage={canManage} />)}</div> : <Empty title="No exams yet" detail="Create an exam to schedule a lab session." />}
      {cancel.error && <QueryError error={cancel.error} />}
    </Panel>

    {selectedRoom && <Panel className="mb-5"><PanelTitle>{selectedRoom.name} · assigned PCs</PanelTitle>
      {!targetIds.length ? <Empty title="No PCs assigned" detail="Assign approved devices in Rooms & Labs first." /> : <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(selectedRoom.grid_columns, 10)}, minmax(0, 1fr))` }}>{targetIds.map((id) => { const device = devices.data?.find((item) => item.id === id); const status = statuses.data?.[id]; const position = layout.data?.assignments.find((item) => item.device_id === id); return <div key={id} style={position ? { gridColumn: position.column + 1, gridRow: position.row + 1 } : undefined} className="min-h-16 rounded-md border border-[var(--color-border)] p-2 text-[9px]"><strong className="block truncate">{device?.assigned_name || device?.hostname || id}</strong><StatusBadge value={status?.agent_state ?? "UNKNOWN"} /></div>; })}</div>}
    </Panel>}

    {reportId && <Panel className="print:border-0 print:shadow-none"><PanelTitle aside={<div className="flex gap-2 print:hidden"><Button onClick={() => window.print()}><Download size={14} /> Export / Print PDF</Button><Button onClick={() => setReportId(null)}>Close</Button></div>}>Exam report</PanelTitle>
      {report.isLoading ? <Skeleton /> : report.error ? <QueryError error={report.error} /> : report.data && <div className="mt-3 space-y-3">
        <div><h2 className="m-0 text-base font-bold">{report.data.exam.title}</h2><p className="text-[10px]">{report.data.exam.room_name} · {new Date(report.data.exam.starts_at).toLocaleString()} – {new Date(report.data.exam.ends_at).toLocaleString()} · {report.data.exam.status}</p></div>
        <h3 className="text-xs font-bold">PC integrity status · {report.data.room_grid?.name ?? report.data.exam.room_name} layout</h3>
        <div className="grid gap-2 print:gap-1" style={report.data.room_grid ? {
          gridTemplateColumns: `repeat(${report.data.room_grid.columns}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${report.data.room_grid.rows}, minmax(4rem, auto))`,
        } : undefined}>{report.data.devices.map((device) => <div key={device.device_id}
          style={device.row !== null && device.column !== null ? { gridRow: device.row + 1, gridColumn: device.column + 1 } : undefined}
          className="min-w-0 rounded-md border border-[var(--color-border)] p-2 text-[8px] print:p-1">
          <strong className="block truncate">{device.device_name}</strong><StatusBadge value={device.agent_state} />
          <span className={`mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${device.violation_count > 0 ? "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-200" : "bg-green-100 text-green-800 dark:bg-green-950/50 dark:text-green-200"}`}>
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${device.violation_count > 0 ? "bg-red-600" : "bg-green-600"}`} />
            {device.violation_count} alerts
          </span>
          <button type="button" onClick={() => setEventsDeviceId((current) => current === device.device_id ? null : device.device_id)}
            aria-expanded={eventsDeviceId === device.device_id}
            aria-haspopup="dialog"
            className="mt-1 w-fit rounded border border-[var(--color-border)] px-1.5 py-1 font-semibold hover:bg-[var(--color-surface-muted)] print:hidden">
            View events
          </button>
          {canManage && <button type="button" onClick={() => { setRenameDeviceId((current) => current === device.device_id ? null : device.device_id); setRenameValue(device.device_name); rename.reset(); }}
            className="ml-1 mt-1 w-fit rounded border border-[var(--color-border)] px-1.5 py-1 font-semibold hover:bg-[var(--color-surface-muted)] print:hidden">
            {renameDeviceId === device.device_id ? "Cancel rename" : "Rename PC"}
          </button>}
          <small>Heartbeat: {device.last_heartbeat_at ? new Date(device.last_heartbeat_at).toLocaleString() : "Never"}</small>
        </div>)}</div>
        {renameDeviceId && <form className="flex flex-wrap items-end gap-2 rounded-md border border-[var(--color-border)] p-3 print:hidden"
          onSubmit={(event) => { event.preventDefault(); if (renameDeviceId && renameValue.trim()) rename.mutate({ id: renameDeviceId, name: renameValue.trim() }); }}>
          <label className="text-[10px] font-semibold">New PC name
            <input autoFocus required maxLength={100} value={renameValue} onChange={(event) => setRenameValue(event.target.value)}
              className="mt-1 block h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2" />
          </label>
          <Button disabled={!renameValue.trim() || rename.isPending}>{rename.isPending ? "Saving…" : "Save name"}</Button>
          {rename.error && <span role="alert" className="text-[10px] text-red-700">{rename.error.message}</span>}
        </form>}
        <h3 className="text-xs font-bold">Integrity alerts ({report.data.violations.length})</h3>{report.data.violations.map((item) => { const captureIds = item.details.screenshot_capture_ids; const captureId = item.details.screenshot_capture_id; const captureCount = Array.isArray(captureIds) ? captureIds.length : (typeof captureId === "string" ? 1 : 0); const detail = item.details.remote_ip ?? item.details.name; return <div key={item.id} className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border)] py-2 text-[10px]"><ShieldAlert size={14} />{new Date(item.occurred_at).toLocaleString()} · {item.kind} · {item.severity} · {report.data!.devices.find((d) => d.device_id === item.device_id)?.device_name ?? item.device_id}{typeof detail === "string" && ` · ${detail}`}{captureCount > 0 && <> · <a href="/screenshots" className="underline">Evidence requested ({captureCount} captures)</a></>}</div>; })}
        <p className="text-[8px] text-[var(--color-muted)]">Generated {new Date(report.data.generated_at).toLocaleString()}. Use the browser print dialog to save as PDF.</p>
      </div>}
    </Panel>}
    {eventsDeviceId && report.data && <div className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/45 p-4 print:hidden" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setEventsDeviceId(null); }}>
      <section className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="exam-pc-events-title">
        <div className="flex items-start justify-between gap-3"><div><p className="m-0 text-[9px] font-bold uppercase tracking-wider text-[var(--color-muted)]">EXAM PC EVENTS</p><h2 id="exam-pc-events-title" className="my-1 text-base font-bold">{report.data.devices.find((item) => item.device_id === eventsDeviceId)?.device_name ?? "PC"}</h2></div><button type="button" autoFocus className="rounded p-2 text-[var(--color-muted)] hover:bg-[var(--color-surface-muted)]" aria-label="Close PC events" onClick={() => setEventsDeviceId(null)}><X size={18} /></button></div>
        {report.data.violations.filter((item) => item.device_id === eventsDeviceId).length ?
          <div className="mt-3">{report.data.violations.filter((item) => item.device_id === eventsDeviceId).map((item) => <div key={item.id} className="flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] py-3 text-[10px]">
            <ShieldAlert size={13} /><time>{new Date(item.occurred_at).toLocaleString()}</time><strong>{item.kind}</strong><span>{item.severity}</span>
            {typeof (item.details.remote_ip ?? item.details.name) === "string" && <span>{String(item.details.remote_ip ?? item.details.name)}</span>}
            {Array.isArray(item.details.screenshot_capture_ids) && item.details.screenshot_capture_ids.length > 0 && <a href="/screenshots" className="underline">View evidence ({item.details.screenshot_capture_ids.length})</a>}
          </div>)}</div> : <p className="mb-0 mt-3 text-[10px] text-[var(--color-muted)]">No exam alerts recorded for this PC.</p>}
      </section>
    </div>}
  </div>;
}

function ExamCard({ exam, onReport, onCancel, canManage }: { exam: Awaited<ReturnType<typeof examsApi.list>>[number]; onReport: () => void; onCancel: () => void; canManage: boolean }) {
  return <article className="rounded-lg border border-[var(--color-border)] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><CalendarClock size={15} /><strong className="text-xs">{exam.title}</strong><StatusBadge value={exam.status} /></div><div className="flex gap-2"><Button onClick={onReport}>Report ({exam.violations})</Button>{canManage && ["SCHEDULED", "ACTIVE"].includes(exam.status) && <Button className="text-red-600" onClick={onCancel}>Cancel</Button>}</div></div><p className="mb-1 text-[9px] text-[var(--color-muted)]">{exam.room_name} · {exam.device_ids.length} PCs · {new Date(exam.starts_at).toLocaleString()} – {new Date(exam.ends_at).toLocaleString()}</p><p className="m-0 text-[8px] text-amber-700">Desired policy saved · agent enforcement status not yet reported</p></article>;
}
