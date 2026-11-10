import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Radio, ShieldCheck, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { devicesApi } from "./api";
import { NetworkInterfaces, OperatingSystemUptime, SystemTelemetry } from "./SystemTelemetry";
import {
  Button,
  ComingSoon,
  PageHeader,
  Panel,
  PanelTitle,
  QueryError,
  Skeleton,
  StatusBadge,
} from "../../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { canManageLabs } from "../auth/api";
import { useToast } from "../../components/Toast";
import { DeviceSoftware } from "../software/DeviceSoftware";
import { DeviceRdpAccess } from "./DeviceRdpAccess";
import { DeviceProcesses } from "./DeviceProcesses";
import { shortWindowsUsername } from "./username";
import { PeripheralActivity } from "./PeripheralActivity";

const tabs = [
  "Overview",
  "Hardware",
  "Software",
  "Processes",
  "Network",
  "Remote Access",
  "Peripheral activity",
];
export function DeviceDetailPage() {
  const { id = "" } = useParams();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState(searchParams.get("tab") === "Processes" ? "Processes" : "Overview");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { admin } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const statuses = useQuery({
    queryKey: ["device-status", id],
    queryFn: () => devicesApi.status(id),
    refetchInterval: 20_000,
  });
  const telemetry = useQuery({
    queryKey: ["telemetry", id],
    queryFn: () => devicesApi.telemetry(id),
    refetchInterval: 30_000,
  });
  const device = devices.data?.find((d) => d.id === id);
  const deleteDevice = useMutation({
    mutationFn: () => devicesApi.remove(id),
    onSuccess: async () => {
      qc.setQueryData(["devices"], (current: typeof devices.data) =>
        current?.filter((item) => item.id !== id),
      );
      qc.removeQueries({ queryKey: ["device-status", id] });
      qc.removeQueries({ queryKey: ["telemetry", id] });
      qc.removeQueries({ queryKey: ["telemetry-history", id] });
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["devices"] }),
        qc.invalidateQueries({ queryKey: ["rooms"] }),
        qc.invalidateQueries({ queryKey: ["room-layout"] }),
        qc.invalidateQueries({ queryKey: ["statuses"] }),
        qc.invalidateQueries({ queryKey: ["telemetry-summary"] }),
        qc.invalidateQueries({ queryKey: ["audit"] }),
      ]);
      setConfirmDelete(false);
      toast(
        "Device permanently deleted. Enroll it again before it can reconnect.",
      );
      navigate("/devices", { replace: true });
    },
    onError: (error: Error) =>
      toast(`Device was not deleted. ${error.message}`, "error"),
  });
  useEffect(() => {
    const onDeleted = (event: Event) => {
      if ((event as CustomEvent<{ deviceId: string }>).detail?.deviceId !== id)
        return;
      navigate("/devices", { replace: true });
    };
    window.addEventListener("labguard:device-deleted", onDeleted);
    return () =>
      window.removeEventListener("labguard:device-deleted", onDeleted);
  }, [id, navigate]);
  const detailRows = (rows: Array<[string, string | undefined]>) => (
    <div className="grid">
      {rows.map(([label, value], index) => (
        <div
          className={`flex justify-between gap-3 py-2.5 text-[10px] ${index < rows.length - 1 ? "border-b border-[var(--color-border)]" : ""}`}
          key={label}
        >
          <span className="text-[var(--color-muted)]">{label}</span>
          <strong className="max-w-[65%] break-words text-right text-[var(--color-foreground)]">
            {value || "Unavailable"}
          </strong>
        </div>
      ))}
    </div>
  );
  return (
    <>
      <div className="mb-4 flex items-center gap-2 text-[10px] text-[var(--color-muted)]">
        <Link className="text-[var(--color-primary)]" to="/devices">
          Devices
        </Link>
        <ChevronRight size={14} />
        <span>
          {device?.assigned_name || device?.hostname || "Device details"}
        </span>
      </div>
      {devices.isError && <QueryError error={devices.error} />}{" "}
      {statuses.isError && <QueryError error={statuses.error} />}
      {devices.isLoading ? (
        <Skeleton rows={2} />
      ) : device ? (
        <>
          <PageHeader
            eyebrow="DEVICE PROFILE"
            title={device.assigned_name || device.hostname}
            description={
              <span className="font-mono text-[9px] text-[var(--color-muted)]">
                {device.id}
              </span>
            }
            action={
              <div className="flex items-center gap-2">
                <StatusBadge value={statuses.data?.agent_state ?? "UNKNOWN"} />
                {canManageLabs(admin?.role) && (
                  <Button
                    className="border-red-200 text-red-700 dark:border-red-900 dark:text-red-300"
                    onClick={() => setConfirmDelete(true)}
                  >
                    <Trash2 size={15} /> Delete device
                  </Button>
                )}
              </div>
            }
          />
          <div
            className="mb-4 flex gap-5 overflow-auto border-b border-[var(--color-border)]"
            role="tablist"
          >
            {tabs.map((item) => (
              <button
                role="tab"
                aria-selected={tab === item}
                className={`whitespace-nowrap border-0 border-b-2 bg-transparent px-0 pb-2.5 text-[10px] ${tab === item ? "border-[var(--color-primary)] font-semibold text-[var(--color-primary)]" : "border-transparent text-[var(--color-muted)]"}`}
                onClick={() => setTab(item)}
                key={item}
              >
                {item}
                {!["Overview", "Hardware", "Software", "Network", "Remote Access", "Peripheral activity"].includes(item) && (
                  <span className="ml-1 rounded bg-[var(--color-surface-subtle)] px-1 py-0.5 text-[7px] text-[var(--color-muted)]">
                    SOON
                  </span>
                )}
              </button>
            ))}
          </div>
          {tab === "Overview" ? (
            <div className="grid gap-4 min-[981px]:grid-cols-2">
              <Panel>
                <PanelTitle>Device information</PanelTitle>
                {detailRows([
                  ["Hostname", device.hostname],
                  ["Username", shortWindowsUsername(telemetry.data?.snapshot?.operating_system.username) ?? undefined],
                  ["Assigned name", device.assigned_name ?? "Not assigned"],
                  ["Device UUID", device.id],
                  ["Enrollment", device.enrollment_state],
                  ["Agent version", device.agent_version ?? "Unavailable"],
                  ["Enabled", device.enabled ? "Yes" : "No"],
                ])}
              </Panel>
              <Panel>
                <PanelTitle>Connection</PanelTitle>
                <div className="my-3 flex items-center gap-3 border-b border-[var(--color-border)] pb-3">
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
                    <Radio size={20} />
                  </span>
                  <div>
                    <StatusBadge
                      value={statuses.data?.agent_state ?? "UNKNOWN"}
                    />
                    <p className="mt-1.5 text-[9px] text-[var(--color-muted)]">
                      {statuses.data?.network_state
                        ? `Network reachability: ${statuses.data.network_state}`
                        : "Network status unavailable"}
                    </p>
                  </div>
                </div>
                {detailRows([
                  [
                    "Last heartbeat",
                    statuses.data?.last_heartbeat_at
                      ? new Date(
                          statuses.data.last_heartbeat_at,
                        ).toLocaleString()
                      : "No heartbeat recorded",
                  ],
                  [
                    "Last seen",
                    statuses.data?.last_seen_at
                      ? new Date(statuses.data.last_seen_at).toLocaleString()
                      : "Never connected",
                  ],
                  [
                    "Status changed",
                    statuses.data?.changed_at
                      ? new Date(statuses.data.changed_at).toLocaleString()
                      : "—",
                  ],
                ])}
                <div className="mt-3 flex items-center gap-1.5 rounded-lg bg-[var(--color-primary-soft)] p-2.5 text-[9px] text-[var(--color-primary)]">
                  <ShieldCheck size={15} /> Status is based on authenticated
                  server heartbeat receipt.
                </div>
              </Panel>
              <OperatingSystemUptime data={telemetry.data?.snapshot} />
            </div>
          ) : tab === "Software" ? (
            <DeviceSoftware id={id} />
          ) : tab === "Hardware" ? (
            <SystemTelemetry id={id} />
          ) : tab === "Network" ? (
            <NetworkInterfaces data={telemetry.data?.snapshot} />
          ) : tab === "Remote Access" ? (
            canManageLabs(admin?.role) ? <DeviceRdpAccess deviceId={id} /> : <Panel><p className="p-4 text-[10px] text-[var(--color-muted)]">Remote Desktop access requires lab-admin access.</p></Panel>
          ) : tab === "Processes" ? (
            canManageLabs(admin?.role) ? <DeviceProcesses deviceId={id} /> : <Panel><p className="p-4 text-[10px] text-[var(--color-muted)]">Process inspection and termination require lab-admin access.</p></Panel>
          ) : tab === "Peripheral activity" ? (
            <PeripheralActivity deviceId={id} />
          ) : (
            <ComingSoon
              title={`${tab} data isn’t available yet`}
              description="The current server API does not provide this device data. This section will become active when the corresponding backend endpoint is implemented."
            />
          )}
        </>
      ) : (
        !devices.isLoading && (
          <Panel>
            <div className="p-6 text-center text-[11px] text-[var(--color-muted)]">
              Device not found in the current server registry.
            </div>
          </Panel>
        )
      )}
      {confirmDelete && device && (
        <div
          className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/40 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !deleteDevice.isPending)
              setConfirmDelete(false);
          }}
        >
          <section
            className="w-full max-w-[500px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-2xl"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-device-title"
            aria-describedby="delete-device-description"
          >
            <span className="mb-3 grid h-10 w-10 place-items-center rounded-xl bg-[var(--color-danger-soft)] text-[var(--color-danger)]">
              <Trash2 size={18} />
            </span>
            <h2
              id="delete-device-title"
              className="text-lg font-bold text-[var(--color-foreground)]"
            >
              Delete this device permanently?
            </h2>
            <p
              id="delete-device-description"
              className="my-3 text-sm leading-relaxed text-[var(--color-muted)]"
            >
              This permanently removes{" "}
              <strong>{device.assigned_name || device.hostname}</strong> and its
              device record ({device.id}). Its active connection will be closed
              and credentials revoked. To reconnect, it must be enrolled and
              approved again. This action cannot be undone.
            </p>
            {deleteDevice.isError && (
              <div
                className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[11px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
                role="alert"
              >
                Device was not deleted. {deleteDevice.error.message}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button
                disabled={deleteDevice.isPending}
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </Button>
              <Button
                className="bg-[var(--color-danger)] text-white"
                disabled={deleteDevice.isPending}
                onClick={() => deleteDevice.mutate()}
              >
                {deleteDevice.isPending ? "Deleting…" : "Permanently delete"}
              </Button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
