import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import { DragDropProvider, useDraggable, useDroppable } from "@dnd-kit/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  Check,
  ChevronDown,
  Computer,
  GripVertical,
  LayoutGrid,
  Monitor,
  Pencil,
  Plus,
  Presentation,
  Save,
  X,
} from "lucide-react";
import { roomsApi } from "./api";
import { devicesApi } from "../devices/api";
import {
  Button,
  Empty,
  PageHeader,
  Panel,
  PanelTitle,
  QueryError,
  Skeleton,
} from "../../components/ui";
import { canManageLabs } from "../auth/api";
import { useAuth } from "../auth/AuthProvider";
import type { Device, DeviceStatus, Layout, Room } from "../../lib/types";
import { useToast } from "../../components/Toast";

const EMPTY_ASSIGNMENTS: Layout["assignments"] = [];

type DeviceWithStatus = { device: Device; status: DeviceStatus | null };
type DeviceCardProps = DeviceWithStatus & {
  editable: boolean;

  onInspect: (device: Device) => void;
};

function LabStatus({ value }: { value: string }) {
  const label = value.replaceAll("_", " ").toLowerCase();
  const tone =
    value === "ONLINE"
      ? "bg-[var(--color-success-soft)] text-[var(--color-success)]"
      : value === "DELAYED"
        ? "bg-[var(--color-warning-soft)] text-[var(--color-warning)]"
        : value === "OFFLINE"
          ? "bg-[var(--color-danger-soft)] text-[var(--color-danger)]"
          : value === "QUARANTINED"
            ? "bg-[var(--color-danger)] text-white"
            : "bg-[var(--color-surface-subtle)] text-[var(--color-muted)]";
  return (
    <span
      className={`inline-flex max-w-[93px] items-center gap-1 whitespace-nowrap rounded-full px-1.5 py-1 text-[7px] font-bold capitalize ${tone}`}
    >
      <i className="h-1 w-1 rounded-full bg-current" />
      {label}
    </span>
  );
}

function DeviceCard({ device, status, editable, onInspect }: DeviceCardProps) {
  const canDrag =
    editable && device.enabled && device.enrollment_state === "APPROVED";
  const drag = useDraggable({ id: `device:${device.id}`, disabled: !canDrag });
  const state =
    device.enrollment_state === "PENDING"
      ? "PENDING"
      : (status?.agent_state ?? "NEVER_CONNECTED");
  const displayName = device.assigned_name || device.hostname;
  return (
    <article
      ref={drag.ref}
      className={`relative flex min-h-[73px] min-w-0 items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-2 shadow-sm transition hover:border-[var(--color-border-strong)] hover:shadow-md ${drag.isDragging ? "opacity-40" : ""} ${canDrag ? "" : "bg-[var(--color-surface-subtle)]"}`}
    >
      <button
        type="button"
        className="flex min-w-0 flex-1 flex-col items-center gap-2 border-0 bg-transparent p-0.5 text-left"
        onClick={() => onInspect(device)}
        aria-label={`View ${displayName} details`}
      >
        <div className="flex items-center gap-2">
          <span className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
            <Monitor size={19} />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <strong
              className="truncate text-[9px] font-bold text-[var(--color-foreground)]"
              title={displayName}
            >
              {displayName}
            </strong>
            <small className="truncate text-[8px] text-[var(--color-muted)]">
              {device.hostname}
            </small>
          </span>
        </div>
        <LabStatus value={state} />
      </button>

      {canDrag && (
        <button
          ref={drag.handleRef}
          type="button"
          className="grid h-7 w-6 shrink-0 cursor-grab touch-none place-items-center rounded-md border-0 bg-transparent text-[var(--color-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-primary)] active:cursor-grabbing"
          aria-label={`Drag ${displayName}`}
          title="Drag to move"
        >
          <GripVertical size={17} />
        </button>
      )}
    </article>
  );
}

function FloorCell({
  row,
  column,
  device,
  status,
  editable,
  onInspect,
}: {
  row: number;
  column: number;
  device?: Device;
  status: DeviceStatus | null;
  editable: boolean;
  onInspect: (device: Device) => void;
}) {
  const droppable = useDroppable({
    id: `cell:${row}:${column}`,
    disabled: !editable,
  });
  return (
    <div
      ref={droppable.ref}
      className={`relative flex min-h-[135px] min-w-0 flex-col justify-center rounded-lg border p-2 pt-6 transition ${droppable.isDropTarget ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-primary)_18%,transparent)]" : device ? "border-[var(--color-border)] bg-[var(--color-surface)]" : "border-dashed border-[var(--color-border)] bg-[var(--color-surface-subtle)]"}`}
    >
      <span className="absolute left-2 top-2 font-mono text-[8px] font-semibold text-[var(--color-muted)]">
        R{row + 1} · C{column + 1}
      </span>
      {device ? (
        <DeviceCard
          device={device}
          status={status}
          editable={editable}
          onInspect={onInspect}
        />
      ) : (
        <div className="flex min-h-[78px] flex-col items-center justify-center gap-2 text-[var(--color-muted)]">
          <Plus size={17} />
          <span className="text-[9px]">
            {editable ? "Drop computer here" : "Empty workstation"}
          </span>
        </div>
      )}
    </div>
  );
}

function UnassignedRail({
  devices,
  editable,
  onInspect,
}: {
  devices: DeviceWithStatus[];
  editable: boolean;
  onInspect: (device: Device) => void;
}) {
  const drop = useDroppable({ id: "unassigned", disabled: !editable });
  return (
    <aside
      ref={drop.ref}
      className={`sticky top-[82px] flex max-h-[calc(100vh-105px)] min-h-[280px] flex-col overflow-hidden rounded-xl border bg-[var(--color-surface)] transition max-[1120px]:static max-[1120px]:max-h-[370px] ${drop.isDropTarget ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-primary)_18%,transparent)]" : "border-[var(--color-border)]"}`}
    >
      <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] p-4">
        <div>
          <h3 className="mb-1 text-xs font-bold text-[var(--color-foreground)]">
            Unassigned
          </h3>
          <p className="m-0 text-[8px] leading-relaxed text-[var(--color-muted)]">
            Drag a computer into an open workstation.
          </p>
        </div>
        <span className="grid h-6 min-w-6 place-items-center rounded-full bg-[var(--color-primary-soft)] px-1.5 text-[9px] font-bold text-[var(--color-primary)]">
          {devices.length}
        </span>
      </div>
      <div className="flex flex-col gap-2 overflow-auto p-2.5 max-[1120px]:grid max-[1120px]:grid-cols-[repeat(auto-fit,minmax(220px,1fr))] max-[680px]:grid-cols-1">
        {devices.length ? (
          devices.map(({ device, status }) => (
            <DeviceCard
              key={device.id}
              device={device}
              status={status}
              editable={editable}
              onInspect={onInspect}
            />
          ))
        ) : (
          <div className="flex flex-col items-center gap-2 p-6 text-center text-[var(--color-muted)]">
            <Check size={19} className="text-[var(--color-success)]" />
            <strong className="text-[9px] text-[var(--color-foreground)]">
              All approved devices are placed
            </strong>
            <span className="text-[8px] leading-relaxed">
              Drag a device here to remove it from the floor plan.
            </span>
          </div>
        )}
      </div>
      {editable && (
        <div className="mt-auto flex items-center justify-center gap-1.5 border-t border-[var(--color-border)] px-2 py-3 text-[8px] text-[var(--color-muted)]">
          <ArrowDown size={14} />
          Drop an assigned computer here to unassign it
        </div>
      )}
    </aside>
  );
}

function DeviceInspector({
  item,
  status,
  coordinate,
  onClose,
}: {
  item: Device;
  status: DeviceStatus | null;
  coordinate?: string;
  onClose: () => void;
}) {
  const state =
    item.enrollment_state === "PENDING"
      ? "PENDING"
      : (status?.agent_state ?? "NEVER_CONNECTED");
  return (
    <div
      className="fixed inset-0 z-[100] flex justify-end bg-slate-950/25"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="h-full w-full max-w-[390px] overflow-auto bg-[var(--color-surface)] p-6 shadow-[-12px_0_35px_rgb(13_32_53/.16)]"
        role="dialog"
        aria-modal="true"
        aria-label={`${item.assigned_name || item.hostname} details`}
      >
        <div className="mb-5 flex items-center justify-between">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
            <Computer size={21} />
          </span>
          <button
            className="grid h-8 w-8 place-items-center rounded-md border-0 bg-transparent text-[var(--color-muted)] hover:bg-[var(--color-surface-subtle)]"
            onClick={onClose}
            aria-label="Close device details"
          >
            <X size={18} />
          </button>
        </div>
        <p className="eyebrow mb-1.5">DEVICE DETAILS</p>
        <h2 className="mb-1 text-xl font-bold text-[var(--color-foreground)]">
          {item.assigned_name || item.hostname}
        </h2>
        <p className="mb-3 text-[10px] text-[var(--color-muted)]">
          {item.hostname}
        </p>
        <LabStatus value={state} />
        <dl className="mt-5 grid">
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">
              Assigned name
            </dt>
            <dd className="max-w-[65%] text-right text-[9px] text-[var(--color-foreground)]">
              {item.assigned_name || "Not assigned"}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">Device ID</dt>
            <dd className="max-w-[65%] break-all text-right font-mono text-[9px] text-[var(--color-foreground)]">
              {item.id}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">Enrollment</dt>
            <dd className="text-right text-[9px] text-[var(--color-foreground)]">
              {item.enrollment_state}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">
              Agent version
            </dt>
            <dd className="text-right text-[9px] text-[var(--color-foreground)]">
              {item.agent_version || "Unavailable"}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">Connection</dt>
            <dd className="text-right text-[9px] text-[var(--color-foreground)]">
              {status
                ? status.connected
                  ? "Connected"
                  : "Disconnected"
                : "Not connected"}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">Network</dt>
            <dd className="text-right text-[9px] text-[var(--color-foreground)]">
              {status?.network_state || "Unknown"}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">
              Last heartbeat
            </dt>
            <dd className="max-w-[65%] text-right text-[9px] text-[var(--color-foreground)]">
              {status?.last_heartbeat_at
                ? new Date(status.last_heartbeat_at).toLocaleString()
                : "None recorded"}
            </dd>
          </div>
          <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5">
            <dt className="text-[9px] text-[var(--color-muted)]">
              Workstation
            </dt>
            <dd className="text-right text-[9px] text-[var(--color-foreground)]">
              {coordinate || "Unassigned"}
            </dd>
          </div>
        </dl>
        <p className="mt-4 rounded-lg bg-[var(--color-surface-subtle)] p-2.5 text-[8px] leading-relaxed text-[var(--color-muted)]">
          Status is based on authenticated heartbeats received by the server.
        </p>
        <a
          href={`/devices/${item.id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex rounded-lg bg-slate-800 px-4 py-2 text-[10px] font-semibold text-slate-300 hover:bg-slate-700"
        >
          View full device details
        </a>
      </aside>
    </div>
  );
}

function assignmentsEqual(a: Layout["assignments"], b: Layout["assignments"]) {
  const normalize = (items: Layout["assignments"]) =>
    [...items].sort((x, y) => x.device_id.localeCompare(y.device_id));
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));
}

function isValidLayout(layout: Layout) {
  const { grid_rows: rows, grid_columns: columns } = layout.room;
  if (
    !Number.isInteger(rows) ||
    !Number.isInteger(columns) ||
    rows < 1 ||
    rows > 100 ||
    columns < 1 ||
    columns > 100
  )
    return false;
  if (layout.assignments.length > 1000) return false;
  const devices = new Set<string>();
  const cells = new Set<string>();
  for (const assignment of layout.assignments) {
    const cell = `${assignment.row}:${assignment.column}`;
    if (
      !Number.isInteger(assignment.row) ||
      !Number.isInteger(assignment.column) ||
      assignment.row < 0 ||
      assignment.column < 0 ||
      assignment.row >= rows ||
      assignment.column >= columns
    )
      return false;
    if (devices.has(assignment.device_id) || cells.has(cell)) return false;
    devices.add(assignment.device_id);
    cells.add(cell);
  }
  return true;
}

export function RoomsPage() {
  const { admin } = useAuth();
  const toast = useToast();
  const editable = canManageLabs(admin?.role);
  const qc = useQueryClient();
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: roomsApi.list });
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const statusIds = devices.data?.map((device) => device.id) ?? [];
  const statuses = useQuery({
    queryKey: ["statuses", statusIds],
    queryFn: () => devicesApi.statuses(devices.data ?? []),
    enabled: !!devices.data?.length,
    refetchInterval: false,
  });
  const [selectedRoomId, setSelectedRoomId] = useState("");
  const [loadedRoomId, setLoadedRoomId] = useState("");
  const [draft, setDraft] = useState<Layout | null>(null);
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [editingRoom, setEditingRoom] = useState<Room | null>(null);
  const [creatingRoom, setCreatingRoom] = useState(false);
  const [notice, setNotice] = useState("");
  const layout = useQuery({
    queryKey: ["room-layout", selectedRoomId],
    queryFn: () => roomsApi.layout(selectedRoomId),
    enabled: !!selectedRoomId,
  });
  const selectedRoom =
    rooms.data?.find((room) => room.id === selectedRoomId) ?? null;
  const statusById = useMemo(
    () =>
      new Map(
        (statuses.data ?? [])
          .filter((item): item is DeviceStatus => item !== null)
          .map((item) => [item.device_id, item]),
      ),
    [statuses.data],
  );

  useEffect(() => {
    const onDeviceDeleted = (event: Event) => {
      const id = (event as CustomEvent<{ deviceId: string }>).detail?.deviceId;
      if (!id) return;
      setSelectedDevice((current) => (current?.id === id ? null : current));
      setDraft((current) =>
        current
          ? {
              ...current,
              assignments: current.assignments.filter(
                (item) => item.device_id !== id,
              ),
            }
          : current,
      );
      void qc.invalidateQueries({ queryKey: ["room-layout"] });
    };
    window.addEventListener("labguard:device-deleted", onDeviceDeleted);
    return () =>
      window.removeEventListener("labguard:device-deleted", onDeviceDeleted);
  }, [qc]);

  useEffect(() => {
    if (!selectedRoomId && rooms.data?.length)
      setSelectedRoomId(rooms.data[0].id);
  }, [rooms.data, selectedRoomId]);
  useEffect(() => {
    if (
      layout.data &&
      layout.data.room.id === selectedRoomId &&
      loadedRoomId !== selectedRoomId
    ) {
      setDraft(structuredClone(layout.data));
      setLoadedRoomId(selectedRoomId);
    }
  }, [layout.data, selectedRoomId, loadedRoomId]);

  const saveRoom = useMutation({
    mutationFn: (room: Room) =>
      room.id
        ? roomsApi.update(room)
        : roomsApi.create({
            name: room.name,
            description: room.description,
            grid_rows: room.grid_rows,
            grid_columns: room.grid_columns,
          }),
    onSuccess: async (saved) => {
      await qc.invalidateQueries({ queryKey: ["rooms"] });
      setEditingRoom(null);
      setCreatingRoom(false);
      if (creatingRoom || !selectedRoomId) {
        setSelectedRoomId(saved.id);
        setLoadedRoomId("");
        setDraft(null);
      }
      toast("Room saved.");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const saveLayout = useMutation({
    mutationFn: (value: Layout) => roomsApi.saveLayout(value.room.id, value),
    onSuccess: (result) => {
      setDraft(structuredClone(result));
      setLoadedRoomId(result.room.id);
      qc.setQueryData(["room-layout", result.room.id], result);
      void qc.invalidateQueries({ queryKey: ["rooms"] });
      setNotice("Floor plan saved.");
      toast("Floor plan saved.");
    },
    onError: (error: Error) => {
      setNotice(error.message);
      toast(
        `Layout was not saved. Your changes are still here. ${error.message}`,
        "error",
      );
    },
  });

  const savedLayout = layout.data;
  const layoutIsValid = !!draft && isValidLayout(draft);
  const isDirty =
    !!draft &&
    !!savedLayout &&
    (draft.room.grid_rows !== savedLayout.room.grid_rows ||
      draft.room.grid_columns !== savedLayout.room.grid_columns ||
      !assignmentsEqual(draft.assignments, savedLayout.assignments));
  const assignedIds = new Set(
    draft?.assignments.map((item) => item.device_id) ??
      EMPTY_ASSIGNMENTS.map((item) => item.device_id),
  );
  const eligibleDevices = (devices.data ?? []).filter(
    (device) => device.enabled && device.enrollment_state === "APPROVED",
  );
  const unassigned = eligibleDevices
    .filter((device) => !assignedIds.has(device.id))
    .map((device) => ({ device, status: statusById.get(device.id) ?? null }));
  const pending = (devices.data ?? []).filter(
    (device) => device.enrollment_state === "PENDING",
  );
  const assignedDevices = (draft?.assignments ?? EMPTY_ASSIGNMENTS)
    .map((assignment) => ({
      assignment,
      device: devices.data?.find(
        (device) => device.id === assignment.device_id,
      ),
    }))
    .filter(
      (
        item,
      ): item is {
        assignment: Layout["assignments"][number];
        device: Device;
      } => !!item.device,
    );
  const stats = {
    assigned: draft?.assignments.length ?? 0,
    online: assignedDevices.filter(
      (item) => statusById.get(item.device.id)?.agent_state === "ONLINE",
    ).length,
    delayed: assignedDevices.filter(
      (item) => statusById.get(item.device.id)?.agent_state === "DELAYED",
    ).length,
    offline: assignedDevices.filter((item) =>
      ["OFFLINE", "NEVER_CONNECTED"].includes(
        statusById.get(item.device.id)?.agent_state ?? "NEVER_CONNECTED",
      ),
    ).length,
  };
  const inspectorStatus = selectedDevice
    ? (statusById.get(selectedDevice.id) ?? null)
    : null;
  const inspectorAssignment = selectedDevice
    ? draft?.assignments.find((item) => item.device_id === selectedDevice.id)
    : undefined;
  const gridStyle: CSSProperties | undefined = draft
    ? {
        gridTemplateColumns: `repeat(${draft.room.grid_columns}, minmax(164px, 1fr))`,
        minWidth: `max(100%, ${draft.room.grid_columns * 164}px)`,
      }
    : undefined;

  const setRoom = (roomId: string) => {
    if (roomId === selectedRoomId) return;
    if (
      isDirty &&
      !window.confirm("Discard unsaved floor plan changes and switch rooms?")
    )
      return;
    setSelectedRoomId(roomId);
    setLoadedRoomId("");
    setDraft(null);
    setSelectedDevice(null);
    setNotice("");
  };
  const handleDrop = (
    event: Parameters<
      NonNullable<React.ComponentProps<typeof DragDropProvider>["onDragEnd"]>
    >[0],
  ) => {
    if (!draft || !editable || event.canceled || !event.operation.target)
      return;
    const sourceId = event.operation.source?.id;
    if (sourceId === undefined || sourceId === null) return;
    const source = String(sourceId);
    if (!source.startsWith("device:")) return;
    const deviceId = source.slice("device:".length);
    const targetId = String(event.operation.target.id);
    if (targetId === "unassigned") {
      setDraft({
        ...draft,
        assignments: draft.assignments.filter(
          (item) => item.device_id !== deviceId,
        ),
      });
      return;
    }
    const match = /^cell:(\d+):(\d+)$/.exec(targetId);
    if (!match) return;
    const row = Number(match[1]);
    const column = Number(match[2]);
    if (
      !Number.isInteger(row) ||
      !Number.isInteger(column) ||
      row < 0 ||
      column < 0 ||
      row >= draft.room.grid_rows ||
      column >= draft.room.grid_columns
    )
      return;
    const sourceAssignment = draft.assignments.find(
      (item) => item.device_id === deviceId,
    );
    const targetAssignment = draft.assignments.find(
      (item) => item.row === row && item.column === column,
    );
    if (
      sourceAssignment &&
      sourceAssignment.row === row &&
      sourceAssignment.column === column
    )
      return;
    let assignments = draft.assignments.filter(
      (item) => item.device_id !== deviceId,
    );
    if (sourceAssignment && targetAssignment) {
      assignments = assignments.map((item) =>
        item.device_id === targetAssignment.device_id
          ? {
              ...item,
              row: sourceAssignment.row,
              column: sourceAssignment.column,
            }
          : item,
      );
    } else if (targetAssignment) {
      assignments = assignments.filter(
        (item) => item.device_id !== targetAssignment.device_id,
      );
    }
    assignments.push({ device_id: deviceId, row, column });
    setDraft({
      ...draft,
      assignments: assignments.sort(
        (a, b) => a.row - b.row || a.column - b.column,
      ),
    });
  };

  const blankRoom = (): Room => ({
    id: "",
    name: "",
    description: "",
    grid_rows: 5,
    grid_columns: 8,
  });
  const closeRoomForm = () => {
    setEditingRoom(null);
    setCreatingRoom(false);
  };

  return (
    <>
      <PageHeader
        eyebrow="LAB ORGANIZATION"
        title="Rooms & labs"
        description="Arrange lab computers on an interactive floor plan."
        action={
          <div className="flex flex-wrap items-center gap-2 max-[680px]:w-full">
            {rooms.data?.length ? (
              <label className="relative flex h-9 items-center gap-2 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 text-[10px] text-[var(--color-muted)] max-[680px]:flex-1">
                <span>Room</span>
                <select
                  className="max-w-[190px] appearance-none border-0 bg-transparent pr-5 text-[11px] font-semibold text-[var(--color-foreground)] outline-none max-[680px]:max-w-none max-[680px]:flex-1"
                  value={selectedRoomId}
                  onChange={(event) => setRoom(event.target.value)}
                  aria-label="Select room"
                >
                  {rooms.data.map((room) => (
                    <option key={room.id} value={room.id}>
                      {room.name}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  className="pointer-events-none absolute right-2.5 text-[var(--color-muted)]"
                  size={15}
                />
              </label>
            ) : null}
            {editable && (
              <Button
                className="bg-[var(--color-primary)] text-white hover:brightness-110"
                onClick={() => {
                  setEditingRoom(blankRoom());
                  setCreatingRoom(true);
                }}
              >
                <Plus size={16} /> Add room
              </Button>
            )}
          </div>
        }
      />

      {rooms.isError && <QueryError error={rooms.error} />}
      {notice && (
        <div
          className="my-2 flex items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-[9px] text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300"
          role="status"
        >
          {notice}
          <button
            className="grid place-items-center border-0 bg-transparent text-inherit"
            onClick={() => setNotice("")}
            aria-label="Dismiss notice"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {(editingRoom || creatingRoom) && (
        <Panel className="mb-3.5 p-4">
          <PanelTitle>
            {creatingRoom ? "Create room" : "Edit room details"}
          </PanelTitle>
          <form
            className="grid items-end gap-2.5 pt-3 max-[1120px]:grid-cols-2 max-[680px]:grid-cols-1"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (editingRoom) saveRoom.mutate(editingRoom);
            }}
          >
            <label className="flex flex-col gap-1.5 text-[9px] font-semibold text-[var(--color-muted)]">
              Room name
              <input
                className="h-[34px] rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)] outline-none"
                required
                maxLength={100}
                value={editingRoom?.name ?? ""}
                onChange={(event) =>
                  editingRoom &&
                  setEditingRoom({ ...editingRoom, name: event.target.value })
                }
              />
            </label>
            <label className="flex flex-col gap-1.5 text-[9px] font-semibold text-[var(--color-muted)]">
              Description
              <input
                className="h-[34px] rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)] outline-none"
                maxLength={500}
                value={editingRoom?.description ?? ""}
                onChange={(event) =>
                  editingRoom &&
                  setEditingRoom({
                    ...editingRoom,
                    description: event.target.value,
                  })
                }
              />
            </label>
            {creatingRoom && (
              <>
                <label className="flex flex-col gap-1.5 text-[9px] font-semibold text-[var(--color-muted)]">
                  Rows
                  <input
                    className="h-[34px] rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)] outline-none"
                    type="number"
                    min={1}
                    max={100}
                    value={editingRoom?.grid_rows ?? 5}
                    onChange={(event) =>
                      editingRoom &&
                      setEditingRoom({
                        ...editingRoom,
                        grid_rows: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label className="flex flex-col gap-1.5 text-[9px] font-semibold text-[var(--color-muted)]">
                  Columns
                  <input
                    className="h-[34px] rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 text-[10px] text-[var(--color-foreground)] outline-none"
                    type="number"
                    min={1}
                    max={100}
                    value={editingRoom?.grid_columns ?? 8}
                    onChange={(event) =>
                      editingRoom &&
                      setEditingRoom({
                        ...editingRoom,
                        grid_columns: Number(event.target.value),
                      })
                    }
                  />
                </label>
              </>
            )}
            <div className="flex gap-1.5 max-[1120px]:col-span-full max-[680px]:col-auto">
              <Button type="button" onClick={closeRoomForm}>
                Cancel
              </Button>
              <Button
                className="bg-[var(--color-primary)] text-white hover:brightness-110"
                type="submit"
                disabled={saveRoom.isPending || !editingRoom?.name.trim()}
              >
                <Save size={15} />
                {saveRoom.isPending
                  ? "Saving…"
                  : creatingRoom
                    ? "Create room"
                    : "Save details"}
              </Button>
            </div>
          </form>
        </Panel>
      )}

      {rooms.isLoading ? (
        <Panel>
          <Skeleton rows={4} />
        </Panel>
      ) : !rooms.data?.length ? (
        <Panel>
          <Empty
            title="No rooms configured"
            detail="Create a room to start building your laboratory floor plan."
          />
        </Panel>
      ) : (
        selectedRoom && (
          <>
            {editingRoom === null && (
              <div className="mb-4 flex items-center justify-between gap-4 max-[680px]:items-start">
                <div>
                  <span className="text-[8px] font-bold tracking-[1.3px] text-[var(--color-muted)]">
                    FLOOR PLAN
                  </span>
                  <h2 className="my-1 text-[19px] font-bold tracking-tight text-[var(--color-foreground)]">
                    {selectedRoom.name}
                  </h2>
                  <p className="m-0 text-[10px] text-[var(--color-muted)]">
                    {selectedRoom.description ||
                      "Computer workstations and room status"}
                  </p>
                </div>
                {editable && (
                  <Button
                    onClick={() => {
                      setEditingRoom({ ...selectedRoom });
                      setCreatingRoom(false);
                    }}
                  >
                    <Pencil size={15} /> Edit room
                  </Button>
                )}
              </div>
            )}
            {layout.isLoading && (
              <Panel className="p-3.5">
                <Skeleton rows={7} />
              </Panel>
            )}
            {layout.isError && (
              <Panel>
                <QueryError error={layout.error} />
                <Button onClick={() => void layout.refetch()}>
                  Retry floor plan
                </Button>
              </Panel>
            )}
            {draft && savedLayout && (
              <DragDropProvider onDragEnd={handleDrop}>
                <div className="grid items-start gap-3.5 min-[1121px]:grid-cols-[minmax(0,1fr)_285px]">
                  <div className="min-w-0">
                    <Panel className="overflow-hidden p-0">
                      <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] p-4 max-[680px]:items-start max-[680px]:flex-col">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <span className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
                            <LayoutGrid size={18} />
                          </span>
                          <div className="flex flex-col gap-1">
                            <strong className="text-[11px] text-[var(--color-foreground)]">
                              {selectedRoom.name} floor plan
                            </strong>
                            <span className="text-[9px] text-[var(--color-muted)]">
                              {draft.room.grid_rows} rows ×{" "}
                              {draft.room.grid_columns} columns
                            </span>
                          </div>
                        </div>
                        {editable && (
                          <div className="flex gap-2 max-[680px]:w-full max-[680px]:justify-end">
                            <label className="flex items-center gap-1.5 text-[9px] text-[var(--color-muted)]">
                              Rows
                              <input
                                className="h-7 w-12 rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-1 text-[10px] text-[var(--color-foreground)]"
                                aria-label="Grid rows"
                                type="number"
                                min={1}
                                max={100}
                                value={draft.room.grid_rows}
                                onChange={(event) =>
                                  setDraft({
                                    ...draft,
                                    room: {
                                      ...draft.room,
                                      grid_rows: Number(event.target.value),
                                    },
                                  })
                                }
                              />
                            </label>
                            <label className="flex items-center gap-1.5 text-[9px] text-[var(--color-muted)]">
                              Columns
                              <input
                                className="h-7 w-12 rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-1 text-[10px] text-[var(--color-foreground)]"
                                aria-label="Grid columns"
                                type="number"
                                min={1}
                                max={100}
                                value={draft.room.grid_columns}
                                onChange={(event) =>
                                  setDraft({
                                    ...draft,
                                    room: {
                                      ...draft.room,
                                      grid_columns: Number(event.target.value),
                                    },
                                  })
                                }
                              />
                            </label>
                          </div>
                        )}
                      </div>
                      <div className="grid grid-cols-5 gap-px border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] p-2.5 max-[680px]:grid-cols-3">
                        {[
                          [
                            "Assigned",
                            stats.assigned,
                            "text-[var(--color-foreground)]",
                          ],
                          [
                            "Online",
                            stats.online,
                            "text-[var(--color-success)]",
                          ],
                          [
                            "Delayed",
                            stats.delayed,
                            "text-[var(--color-warning)]",
                          ],
                          [
                            "Offline",
                            stats.offline,
                            "text-[var(--color-danger)]",
                          ],
                          [
                            "Unassigned",
                            unassigned.length,
                            "text-[var(--color-primary)]",
                          ],
                        ].map(([label, value, tone]) => (
                          <div
                            className="flex flex-col gap-1 border-r border-[var(--color-border)] px-2 py-1 last:border-0"
                            key={label as string}
                          >
                            <span className="text-[8px] uppercase tracking-[.55px] text-[var(--color-muted)]">
                              {label}
                            </span>
                            <strong
                              className={`text-base font-bold ${tone as string}`}
                            >
                              {value}
                            </strong>
                          </div>
                        ))}
                      </div>
                      <div
                        className="max-w-full overflow-auto overscroll-x-contain bg-[var(--color-surface-subtle)] p-4"
                        aria-label="Scrollable laboratory floor plan"
                      >
                        <div
                          className="grid items-stretch gap-2"
                          style={gridStyle}
                        >
                          <div className="col-span-full mb-1 grid min-h-[82px] grid-cols-[30px_1fr_30px] grid-rows-[auto_auto] items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-primary-soft)] px-3 py-2 text-[var(--color-muted)]">
                            <span className="row-start-1 flex items-center">
                              <ArrowDown size={16} />
                            </span>
                            <span className="col-start-2 row-start-1 text-center text-[8px] font-bold tracking-[1.35px]">
                              FRONT OF ROOM
                            </span>
                            <div className="col-span-3 row-start-2 flex min-w-[170px] justify-self-center items-center justify-center gap-2 rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-4 py-2 text-[var(--color-primary)] shadow-sm">
                              <Presentation size={17} />
                              <strong className="text-[10px]">
                                Instructor desk
                              </strong>
                            </div>
                          </div>
                          {Array.from(
                            {
                              length:
                                draft.room.grid_rows * draft.room.grid_columns,
                            },
                            (_, index) => {
                              const row = Math.floor(
                                index / draft.room.grid_columns,
                              );
                              const column = index % draft.room.grid_columns;
                              const assignment = draft.assignments.find(
                                (item) =>
                                  item.row === row && item.column === column,
                              );
                              const device = assignment
                                ? devices.data?.find(
                                    (item) => item.id === assignment.device_id,
                                  )
                                : undefined;
                              return (
                                <FloorCell
                                  key={`${row}:${column}`}
                                  row={row}
                                  column={column}
                                  device={device}
                                  status={
                                    device
                                      ? (statusById.get(device.id) ?? null)
                                      : null
                                  }
                                  editable={editable}
                                  onInspect={setSelectedDevice}
                                />
                              );
                            },
                          )}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-4 px-4 py-3 text-[8px] text-[var(--color-muted)]">
                        <span className="flex items-center gap-1.5">
                          <i className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
                          Online
                        </span>
                        <span className="flex items-center gap-1.5">
                          <i className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                          Delayed
                        </span>
                        <span className="flex items-center gap-1.5">
                          <i className="h-1.5 w-1.5 rounded-full bg-red-500" />
                          Offline
                        </span>
                        <span className="flex items-center gap-1.5">
                          <i className="h-1.5 w-1.5 rounded-full bg-red-900" />
                          Quarantined
                        </span>
                        <span className="flex items-center gap-1.5">
                          <i className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                          Pending
                        </span>
                      </div>
                    </Panel>
                    {editable && isDirty && (
                      <div className="sticky bottom-3 z-[5] mt-3 flex items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 shadow-lg dark:border-blue-900 dark:bg-blue-950/40 max-[680px]:items-start max-[680px]:flex-col">
                        <span className="flex flex-col gap-1">
                          <strong className="text-[9px] text-blue-900 dark:text-blue-200">
                            Unsaved floor plan changes
                          </strong>
                          <small className="text-[8px] text-blue-700 dark:text-blue-300">
                            Changes stay local until you save.
                          </small>
                        </span>
                        <div className="flex gap-2 max-[680px]:w-full max-[680px]:justify-end">
                          <Button
                            disabled={saveLayout.isPending}
                            onClick={() => {
                              setDraft(structuredClone(savedLayout));
                              setNotice("Unsaved changes discarded.");
                            }}
                          >
                            Discard
                          </Button>
                          <Button
                            className="bg-[var(--color-primary)] text-white hover:brightness-110"
                            disabled={saveLayout.isPending || !layoutIsValid}
                            onClick={() => saveLayout.mutate(draft)}
                          >
                            <Save size={15} />
                            {saveLayout.isPending
                              ? "Saving…"
                              : "Save floor plan"}
                          </Button>
                        </div>
                      </div>
                    )}
                    {editable && draft && !layoutIsValid && (
                      <div
                        className="my-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[8px] leading-relaxed text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300"
                        role="alert"
                      >
                        Grid dimensions must be whole numbers from 1 to 100.
                        Each device and cell can only be assigned once, and
                        placements must fit inside the grid.
                      </div>
                    )}
                    {saveLayout.isError && (
                      <div
                        className="my-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[9px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
                        role="alert"
                      >
                        {saveLayout.error.message} Your edits are preserved.
                        Adjust the layout and try again.
                      </div>
                    )}
                  </div>
                  <UnassignedRail
                    devices={unassigned}
                    editable={editable}
                    onInspect={setSelectedDevice}
                  />
                </div>
                {pending.length > 0 && (
                  <div className="mt-2.5 flex items-center gap-2 text-[9px] text-[var(--color-muted)]">
                    <LabStatus value="PENDING" />
                    <span>
                      {pending.length} device{pending.length === 1 ? "" : "s"}{" "}
                      awaiting enrollment approval cannot be placed yet.
                    </span>
                  </div>
                )}
                {selectedDevice && (
                  <DeviceInspector
                    item={selectedDevice}
                    status={inspectorStatus}
                    coordinate={
                      inspectorAssignment
                        ? `Row ${inspectorAssignment.row + 1}, column ${inspectorAssignment.column + 1}`
                        : undefined
                    }
                    onClose={() => setSelectedDevice(null)}
                  />
                )}
              </DragDropProvider>
            )}
          </>
        )
      )}
    </>
  );
}
