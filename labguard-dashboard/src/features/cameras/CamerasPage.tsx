import { useState, type FormEvent } from "react";
import { Camera, CircleAlert, Plus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Empty, PageHeader, Panel, PanelTitle, QueryError, Skeleton, StatusBadge } from "../../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { roomsApi } from "../rooms/api";
import { cameraApi } from "./api";

export function CamerasPage() {
  const { admin } = useAuth();
  const queryClient = useQueryClient();
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: roomsApi.list });
  const [roomId, setRoomId] = useState("");
  const [name, setName] = useState("");
  const [streamUri, setStreamUri] = useState("");
  const cameras = useQuery({ queryKey: ["lab-cameras", roomId], queryFn: () => cameraApi.list(roomId || undefined), refetchInterval: 5_000 });
  const detections = useQuery({ queryKey: ["lab-camera-detections", roomId], queryFn: () => cameraApi.detections(roomId || undefined), refetchInterval: 5_000 });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["lab-cameras"] }),
      queryClient.invalidateQueries({ queryKey: ["lab-camera-detections"] }),
    ]);
  };
  const create = useMutation({ mutationFn: () => cameraApi.create(roomId, name.trim(), streamUri.trim()), onSuccess: async () => { setName(""); setStreamUri(""); await refresh(); } });
  const update = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => cameraApi.update(id, { enabled }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: cameraApi.remove, onSuccess: refresh });
  const canManage = admin?.role === "LAB_ADMIN" || admin?.role === "SUPER_ADMIN";
  const submit = (event: FormEvent) => { event.preventDefault(); if (roomId && name.trim() && streamUri.trim()) create.mutate(); };

  return <div className="mx-auto max-w-6xl p-4 md:p-6">
    <PageHeader eyebrow="ROOM MONITORING" title="Lab cameras" description="View recent frames and object detections from disclosed, institution-authorized RTSP cameras assigned to each lab." />
    {(rooms.error || cameras.error || detections.error) && <QueryError error={rooms.error ?? cameras.error ?? detections.error} />}
    <Panel className="mb-5">
      <PanelTitle aside={<span className="text-[9px] text-[var(--color-muted)]">Camera status and detections refresh every 5 seconds</span>}>Camera coverage</PanelTitle>
      <label className="mt-3 block max-w-sm text-[10px] font-semibold">Lab
        <select value={roomId} onChange={(event) => setRoomId(event.target.value)} className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2">
          <option value="">All labs</option>{rooms.data?.map((room) => <option key={room.id} value={room.id}>{room.name}</option>)}
        </select>
      </label>
      {cameras.isLoading ? <Skeleton rows={3} /> : cameras.data?.length ? <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {cameras.data.map((camera) => <article key={camera.id} className="overflow-hidden rounded-lg border border-[var(--color-border)]">
          {camera.state === "ONLINE" && camera.last_frame_at ? <img src={cameraApi.frameUrl(camera.id, camera.last_frame_at)} alt={`Latest frame from ${camera.name}`} className="aspect-video w-full bg-black object-contain" /> :
            <div className="grid aspect-video place-items-center bg-[var(--color-surface-subtle)] text-[10px] text-[var(--color-muted)]"><Camera size={22} />No recent frame</div>}
          <div className="p-3"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-xs">{camera.name}</strong><StatusBadge value={camera.state} /></div>
            <p className="my-1 text-[9px] text-[var(--color-muted)]">{camera.room_name} · {camera.last_frame_at ? new Date(camera.last_frame_at).toLocaleTimeString() : camera.error_code ?? "Waiting for first sample"}</p>
            {camera.error_code && <p className="flex items-center gap-1 text-[9px] text-amber-700"><CircleAlert size={12} />{camera.error_code}</p>}
            {canManage && <div className="mt-2 flex gap-2 print:hidden"><Button disabled={update.isPending} onClick={() => update.mutate({ id: camera.id, enabled: !camera.enabled })}>{camera.enabled ? "Pause" : "Enable"}</Button><Button className="text-red-600" disabled={remove.isPending} onClick={() => { if (window.confirm(`Remove camera ${camera.name} and its detection history?`)) remove.mutate(camera.id); }}><Trash2 size={12} /> Remove</Button></div>}
          </div>
        </article>)}
      </div> : <Empty title="No cameras configured" detail="Add one or more RTSP/IP cameras for a lab." />}
      {(update.error || remove.error) && <QueryError error={update.error ?? remove.error} />}
    </Panel>

    {canManage && <Panel className="mb-5"><PanelTitle>Add an RTSP camera</PanelTitle>
      <form onSubmit={submit} className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="text-[10px] font-semibold">Lab<select required value={roomId} onChange={(event) => setRoomId(event.target.value)} className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2"><option value="">Select a lab</option>{rooms.data?.map((room) => <option key={room.id} value={room.id}>{room.name}</option>)}</select></label>
        <label className="text-[10px] font-semibold">Camera name<input required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="Front of Lab" className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2" /></label>
        <label className="text-[10px] font-semibold md:col-span-2">RTSP/RTSPS stream URL<input required type="password" autoComplete="new-password" maxLength={2048} value={streamUri} onChange={(event) => setStreamUri(event.target.value)} placeholder="rtsp://user:password@camera-address/stream" className="mt-1 block h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2" /><small className="font-normal text-[var(--color-muted)]">Credentials are encrypted in the database and never returned to the browser. Use a view-only camera account; prefer RTSPS or an isolated camera VLAN because RTSP may send credentials without transport encryption.</small></label>
        {create.error && <QueryError error={create.error} />}
        <div className="flex items-center gap-2 md:col-span-2"><Button disabled={!roomId || !name.trim() || !streamUri.trim() || create.isPending}><Plus size={13} />{create.isPending ? "Adding…" : "Add camera"}</Button><span className="text-[9px] text-[var(--color-muted)]">Frames are sampled every 10 seconds. A detected-object evidence frame is saved at most once per minute per camera and auto-deleted after 24 hours; other frames are discarded. Up to 8 cameras per lab, 32 total.</span></div>
      </form>
    </Panel>}

    <Panel><PanelTitle>Detected items</PanelTitle>
      {detections.isLoading ? <Skeleton rows={4} /> : detections.data?.length ? <div className="mt-2 divide-y divide-[var(--color-border)]">{detections.data.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-3 py-2 text-[10px]">
        {item.image_available && <a href={cameraApi.evidenceUrl(item.id)} target="_blank" rel="noreferrer" title="Open saved detection frame"><img src={cameraApi.evidenceUrl(item.id)} alt={`Saved frame showing detected ${item.label}`} loading="lazy" className="h-16 w-24 rounded border border-[var(--color-border)] bg-black object-contain" /></a>}
        <div className="min-w-48 flex-1"><strong className="capitalize">{item.label}</strong><span className="text-[var(--color-muted)]"> · {item.camera_name} · {item.room_name}</span><span className="ml-1">× {item.count}</span>{item.image_available && <span className="ml-2 text-[var(--color-muted)]">Image retained for 24h</span>}</div>
        <span className="text-[var(--color-muted)]">{Math.round(item.confidence * 100)}% · {new Date(item.occurred_at).toLocaleString()}</span>
      </div>)}</div> : <Empty title="No target items detected" detail="Detection history appears here when a configured camera sees supported objects." />}
    </Panel>
    <p className="mt-3 text-[9px] text-[var(--color-muted)]">This detector flags visible bottles, cups, bowls, and selected food classes. It cannot tell whether a cup contains coffee or another drink, and detections can be wrong. No faces or identities are analyzed.</p>
  </div>;
}
