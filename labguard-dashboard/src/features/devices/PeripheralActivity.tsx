import { useQuery } from "@tanstack/react-query";
import { Bluetooth, Camera, HardDrive, Keyboard, Printer, Usb } from "lucide-react";
import { Panel, PanelTitle, QueryError, Skeleton } from "../../components/ui";
import { devicesApi } from "./api";
import type { PeripheralEvent } from "../../lib/types";

function categoryName(category: string) {
  const names: Record<string, string> = {
    EXTERNAL_DRIVE: "External drive",
    USB_PERIPHERAL: "USB peripheral",
    INPUT_DEVICE: "Input device",
    BLUETOOTH: "Bluetooth device",
    CAMERA_OR_SCANNER: "Camera or scanner",
    PRINTER: "Printer",
    MODEM: "Modem",
  };
  return names[category] ?? "Peripheral";
}

function PeripheralIcon({ category, storage }: { category: string; storage: boolean }) {
  const props = { size: 17, className: "text-[var(--color-primary)]" };
  if (storage) return <HardDrive {...props} />;
  if (category === "BLUETOOTH") return <Bluetooth {...props} />;
  if (category === "PRINTER") return <Printer {...props} />;
  if (category === "CAMERA_OR_SCANNER") return <Camera {...props} />;
  if (category === "INPUT_DEVICE") return <Keyboard {...props} />;
  if (category === "USB_PERIPHERAL") return <Usb {...props} />;
  return <Usb {...props} />;
}

function EventRow({ item }: { item: PeripheralEvent }) {
  const connected = item.action === "CONNECTED";
  return (
    <div className="flex items-center gap-3 border-b border-[var(--color-border)] py-3 last:border-0">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)]">
        <PeripheralIcon category={item.category} storage={item.is_storage} />
      </span>
      <div className="min-w-0 flex-1">
        <strong className="block truncate text-[11px] text-[var(--color-foreground)]">{item.name}</strong>
        <span className="text-[9px] text-[var(--color-muted)]">{categoryName(item.category)}</span>
      </div>
      <span className={`shrink-0 rounded-full px-2 py-1 text-[8px] font-semibold ${connected ? "bg-[var(--color-success-soft)] text-[var(--color-success)]" : "bg-[var(--color-surface-subtle)] text-[var(--color-muted)]"}`}>
        {connected ? "Connected" : "Disconnected"}
      </span>
      <time className="hidden shrink-0 text-[8px] text-[var(--color-muted)] sm:block">
        {new Date(item.occurred_at).toLocaleString()}
      </time>
    </div>
  );
}

export function PeripheralActivity({ deviceId }: { deviceId: string }) {
  const query = useQuery({
    queryKey: ["device-peripherals", deviceId],
    queryFn: () => devicesApi.peripherals(deviceId),
    refetchInterval: 10_000,
  });
  if (query.isLoading) return <Skeleton rows={5} />;
  if (query.isError) return <QueryError error={query.error} />;
  const activity = query.data!;

  return (
    <div className="grid gap-4">
      <Panel>
        <PanelTitle aside={<span className={`text-[9px] font-semibold ${activity.stale ? "text-amber-600" : "text-[var(--color-success)]"}`}>
          {activity.stale ? "Scan unavailable or stale" : "Live scan"}
        </span>}>
          Connected peripherals ({activity.connected.length})
        </PanelTitle>
        <p className="my-3 text-[9px] leading-relaxed text-[var(--color-muted)]">
          LabGuard reports attached USB devices, input devices, Bluetooth devices, printers, cameras, and external USB drives. It does not read drive contents or track file activity.
          {activity.observed_at && <> Last agent report: {new Date(activity.observed_at).toLocaleString()}.</>}
        </p>
        {activity.connected.length ? activity.connected.map((item) => (
          <div className="flex items-center gap-3 border-b border-[var(--color-border)] py-3 last:border-0" key={item.device_key}>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)]">
              <PeripheralIcon category={item.category} storage={item.is_storage} />
            </span>
            <div className="min-w-0 flex-1">
              <strong className="block truncate text-[11px] text-[var(--color-foreground)]">{item.name}</strong>
              <span className="text-[9px] text-[var(--color-muted)]">{categoryName(item.category)}</span>
            </div>
            <span className="rounded-full bg-[var(--color-success-soft)] px-2 py-1 text-[8px] font-semibold text-[var(--color-success)]">Connected</span>
          </div>
        )) : (
          <div className="py-6 text-center text-[10px] text-[var(--color-muted)]">
            {activity.stale ? "Waiting for a fresh agent scan." : "No monitored peripherals are currently connected."}
          </div>
        )}
      </Panel>

      <Panel>
        <PanelTitle>Connection history</PanelTitle>
        {activity.events.length ? activity.events.map((item) => <EventRow item={item} key={item.id} />) : (
          <div className="py-6 text-center text-[10px] text-[var(--color-muted)]">
            {activity.stale ? "History will appear after the endpoint reports its first scan." : "No connection changes have been recorded."}
          </div>
        )}
      </Panel>
    </div>
  );
}
