import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, HardDrive, Usb } from "lucide-react";
import { PageHeader, Panel, PanelTitle, QueryError, Skeleton, StatusBadge } from "../../components/ui";
import { canManageLabs } from "../auth/api";
import { useAuth } from "../auth/AuthProvider";
import { DeviceRdpAccess } from "./DeviceRdpAccess";
import { devicesApi } from "./api";
import type { Device, DeviceStatus, PeripheralActivity, PeripheralEvent } from "../../lib/types";

function displayName(device: Device) {
  return device.assigned_name || device.hostname;
}

function peripheralLabel(category: string) {
  const labels: Record<string, string> = {
    EXTERNAL_DRIVE: "External drive",
    USB_PERIPHERAL: "USB peripheral",
    INPUT_DEVICE: "Input device",
    BLUETOOTH: "Bluetooth device",
    CAMERA_OR_SCANNER: "Camera or scanner",
    PRINTER: "Printer",
    MODEM: "Modem",
  };
  return labels[category] ?? "Peripheral";
}

type DevicePeripheralResult = {
  device: Device;
  activity: PeripheralActivity | null;
  error: string | null;
};

export function UsbMonitoringPage() {
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list, refetchInterval: 30_000 });
  const deviceIds = (devices.data ?? []).map((device) => device.id).join(",");
  const activity = useQuery({
    queryKey: ["fleet-peripherals", deviceIds],
    enabled: devices.isSuccess,
    queryFn: async (): Promise<DevicePeripheralResult[]> => Promise.all((devices.data ?? []).map(async (device) => {
      try {
        return { device, activity: await devicesApi.peripherals(device.id), error: null };
      } catch (error) {
        return { device, activity: null, error: error instanceof Error ? error.message : "Peripheral status unavailable" };
      }
    })),
    refetchInterval: 10_000,
  });
  const connectedCount = (activity.data ?? []).reduce((sum, result) => sum + (result.activity?.connected.length ?? 0), 0);
  const externalDriveCount = (activity.data ?? []).reduce((sum, result) => sum + (result.activity?.connected.filter((item) => item.is_storage).length ?? 0), 0);
  const events = (activity.data ?? []).flatMap((result) => (result.activity?.events ?? []).map((item) => ({ ...item, deviceName: displayName(result.device) })))
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at)).slice(0, 300);

  return <>
    <PageHeader eyebrow="MONITORING" title="USB Monitoring" description="Connected peripherals and connection history across enrolled devices. Refreshes every 10 seconds." />
    {devices.isError && <QueryError error={devices.error} />}
    {devices.isLoading || activity.isLoading ? <Skeleton rows={6} /> : activity.data && <div className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Panel><p className="text-[9px] text-[var(--color-muted)]">Devices monitored</p><strong className="mt-1 block text-xl">{activity.data.length}</strong></Panel>
        <Panel><p className="text-[9px] text-[var(--color-muted)]">Connected peripherals</p><strong className="mt-1 block text-xl">{connectedCount}</strong></Panel>
        <Panel><p className="text-[9px] text-[var(--color-muted)]">External drives</p><strong className="mt-1 block text-xl">{externalDriveCount}</strong></Panel>
      </div>
      <Panel>
        <PanelTitle>Connected peripherals by device</PanelTitle>
        <p className="my-3 text-[9px] text-[var(--color-muted)]">Reports attached USB devices, input devices, Bluetooth devices, printers, cameras, and external drives. It does not read drive contents or track file activity.</p>
        {activity.data.some((result) => result.error || result.activity?.stale) && <div className="mb-3 rounded border border-amber-500/50 p-2 text-[9px] text-amber-800 dark:text-amber-200">Some endpoints have not reported a fresh peripheral scan. Check the per-device status below.</div>}
        {activity.data.map((result) => {
          const expanded = expandedDevices.has(result.device.id);
          const count = result.activity?.connected.length ?? 0;
          return <div className="border-b border-[var(--color-border)] py-3 last:border-0" key={result.device.id}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <button type="button" aria-expanded={expanded} aria-label={`${expanded ? "Collapse" : "Show"} peripherals for ${displayName(result.device)}`} className="inline-flex items-center gap-1 text-left text-[10px] font-semibold" onClick={() => setExpandedDevices((current) => {
              const next = new Set(current);
              if (next.has(result.device.id)) next.delete(result.device.id);
              else next.add(result.device.id);
              return next;
            })}>
              {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              {displayName(result.device)} <span className="font-normal text-[var(--color-muted)]">· {count} connected</span>
            </button>
            <span className={`rounded-full px-2 py-1 text-[8px] font-semibold ${result.error || result.activity?.stale ? "bg-amber-500/10 text-amber-700" : "bg-[var(--color-success-soft)] text-[var(--color-success)]"}`}>{result.error ? "Unavailable" : result.activity?.stale ? "Stale" : "Live"}</span>
            {result.activity?.observed_at && <span className="text-[8px] text-[var(--color-muted)]">Last report {new Date(result.activity.observed_at).toLocaleString()}</span>}
          </div>
          {expanded && (result.error ? <p className="text-[9px] text-[var(--color-muted)]">{result.error}</p> : result.activity?.connected.length ? <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {result.activity.connected.map((item) => <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] p-2" key={item.device_key}>
              {item.is_storage ? <HardDrive size={16} className="text-[var(--color-primary)]" /> : <Usb size={16} className="text-[var(--color-primary)]" />}
              <div className="min-w-0"><strong className="block truncate text-[9px]">{item.name}</strong><span className="text-[8px] text-[var(--color-muted)]">{peripheralLabel(item.category)} · Connected</span></div>
            </div>)}
          </div> : <p className="text-[9px] text-[var(--color-muted)]">{result.activity?.stale ? "No fresh scan; current connection state may be outdated." : "No monitored peripherals connected."}</p>)}
        </div>;
        })}
        {!activity.data.length && <p className="py-5 text-center text-[10px] text-[var(--color-muted)]">No enrolled devices found.</p>}
      </Panel>
      <Panel>
        <PanelTitle>Recent connection history</PanelTitle>
        {events.length ? <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[700px] text-left text-[10px]">
          <thead><tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]"><th className="p-2">Device</th><th className="p-2">Peripheral</th><th className="p-2">Category</th><th className="p-2">Activity</th><th className="p-2">Time</th></tr></thead>
          <tbody>{events.map((item) => <PeripheralHistoryRow item={item} key={item.id} />)}</tbody>
        </table></div> : <p className="py-6 text-center text-[10px] text-[var(--color-muted)]">No peripheral changes have been reported yet.</p>}
      </Panel>
    </div>}
  </>;
}

function PeripheralHistoryRow({ item }: { item: PeripheralEvent & { deviceName: string } }) {
  return <tr className="border-b border-[var(--color-border)] last:border-0">
    <td className="p-2">{item.deviceName}</td><td className="p-2">{item.name}</td><td className="p-2">{peripheralLabel(item.category)}</td>
    <td className="p-2">{item.action === "CONNECTED" ? "Connected" : "Disconnected"}</td><td className="whitespace-nowrap p-2">{new Date(item.occurred_at).toLocaleString()}</td>
  </tr>;
}

export function FleetRemoteAccessPage() {
  const { admin } = useAuth();
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list, refetchInterval: 30_000 });
  const deviceIds = (devices.data ?? []).map((device) => device.id).join(",");
  const statuses = useQuery({
    queryKey: ["statuses", "remote-access", deviceIds],
    queryFn: () => devicesApi.statuses(devices.data ?? []),
    enabled: Boolean(devices.data?.length),
    refetchInterval: 20_000,
  });
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  useEffect(() => {
    if (!selectedDeviceId && devices.data?.length) setSelectedDeviceId(devices.data[0].id);
    else if (selectedDeviceId && devices.data && !devices.data.some((device) => device.id === selectedDeviceId)) setSelectedDeviceId(devices.data[0]?.id ?? "");
  }, [devices.data, selectedDeviceId]);
  const selectedDevice = devices.data?.find((device) => device.id === selectedDeviceId);
  const statusById = new Map((statuses.data ?? []).filter((status): status is DeviceStatus => Boolean(status)).map((status) => [status.device_id, status]));
  const selectedStatus = selectedDevice ? statusById.get(selectedDevice.id) : undefined;
  const online = selectedStatus?.agent_state === "ONLINE" || selectedStatus?.agent_state === "DELAYED";

  return <>
    <PageHeader eyebrow="REMOTE ACCESS" title="Remote Access" description="Select an enrolled PC to request its temporary Remote Desktop access window." />
    {devices.isError && <QueryError error={devices.error} />}
    {devices.isLoading || (Boolean(devices.data?.length) && statuses.isLoading) ? <Skeleton rows={4} /> : <div className="grid gap-4">
      <Panel>
        <PanelTitle>Choose a device</PanelTitle>
        <p className="my-3 text-[9px] text-[var(--color-muted)]">Only connected, approved Windows endpoints can prepare Remote Desktop. The endpoint remains responsible for Windows account authentication.</p>
        {devices.data?.length ? <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {devices.data.map((device) => {
            const status = statusById.get(device.id);
            return <button type="button" key={device.id} onClick={() => setSelectedDeviceId(device.id)} className={`rounded-lg border p-3 text-left ${selectedDeviceId === device.id ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)]" : "border-[var(--color-border)]"}`}>
              <strong className="block truncate text-[10px]">{displayName(device)}</strong>
              <span className="mt-1 block text-[8px] text-[var(--color-muted)]">{device.hostname}</span>
              <span className="mt-2 inline-flex"><StatusBadge value={status?.agent_state ?? "UNKNOWN"} /></span>
            </button>;
          })}
        </div> : <p className="py-6 text-center text-[10px] text-[var(--color-muted)]">No enrolled devices found.</p>}
      </Panel>
      {selectedDevice && <>
        {!canManageLabs(admin?.role) ? <Panel><p className="text-[10px] text-[var(--color-muted)]">Requesting Remote Desktop access requires lab-admin access.</p></Panel>
          : online ? <DeviceRdpAccess key={selectedDevice.id} deviceId={selectedDevice.id} />
            : <Panel><PanelTitle>{displayName(selectedDevice)}</PanelTitle><p className="py-3 text-[10px] text-[var(--color-muted)]">This device is currently {selectedStatus?.agent_state.toLowerCase() ?? "unreachable"}. It must reconnect before you can request Remote Desktop access.</p></Panel>}
      </>}
    </div>}
  </>;
}
