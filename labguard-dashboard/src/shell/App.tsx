import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  Link,
} from "react-router-dom";
import {
  Activity,
  ChevronDown,
  Command,
  Cpu,
  FileClock,
  Gauge,
  Grid2X2,
  Headphones,
  Laptop,
  Menu,
  Moon,
  Network,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  Sun,
  Usb,
  UserRoundCheck,
  X,
} from "lucide-react";
import { LoginPage, useAuth } from "../features/auth/AuthProvider";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { DevicesPage } from "../features/devices/DevicesPage";
import { DeviceDetailPage } from "../features/devices/DeviceDetailPage";
import { RoomsPage } from "../features/rooms/RoomsPage";
import { EnrollmentPage } from "../features/enrollment/EnrollmentPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { AuditPage } from "../features/audit/AuditPage";
import { SoftwarePage } from "../features/software/SoftwarePage";
import { SoftwareDeploymentPage } from "../features/software/SoftwareDeploymentPage";
import { ProcessMonitoringPage } from "../features/devices/ProcessMonitoringPage";
import { ComingSoon } from "../components/ui";
import type { Device } from "../lib/types";

type Nav = {
  label: string;
  path: string;
  icon: ComponentType<{ size?: number }>;
};
const groups: { title: string; items: Nav[] }[] = [
  {
    title: "WORKSPACE",
    items: [
      { label: "Overview", path: "/", icon: Gauge },
      { label: "Rooms & Labs", path: "/rooms", icon: Grid2X2 },
      { label: "Devices", path: "/devices", icon: Laptop },
      {
        label: "Enrollment Requests",
        path: "/enrollment",
        icon: UserRoundCheck,
      },
    ],
  },
  {
    title: "MONITORING",
    items: [
      { label: "Software Inventory", path: "/software", icon: Package },
      { label: "Software Deployment", path: "/deployment", icon: Cpu },
      { label: "Process Monitoring", path: "/processes", icon: Activity },
      { label: "Network Monitoring", path: "/network", icon: Network },
      { label: "USB Monitoring", path: "/usb", icon: Usb },
      { label: "Remote Access", path: "/remote-access", icon: Headphones },
    ],
  },
  {
    title: "SYSTEM",
    items: [
      { label: "Audit Logs", path: "/audit", icon: FileClock },
      { label: "Settings", path: "/settings", icon: Settings },
    ],
  },
];
function Protected({ children }: { children: React.ReactNode }) {
  const { admin, ready } = useAuth();
  if (!ready) return null;
  return admin ? <>{children}</> : <Navigate to="/login" replace />;
}
function Placeholder({ title }: { title: string }) {
  return (
    <>
      <div className="text-[9px] font-bold tracking-[1.4px] text-[var(--color-muted)]">
        MONITORING
      </div>
      <h1 className="my-1 text-[26px] font-bold tracking-tight text-[var(--color-foreground)]">
        {title}
      </h1>
      <ComingSoon
        title={`${title} is planned`}
        description="The current LabGuard server API does not provide this capability. This page will be enabled when backend support is available."
      />
    </>
  );
}
function Shell({ children }: { children: ReactNode }) {
  const { admin, logout } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = localStorage.getItem("labguard-theme");
    return stored === "dark" || stored === "light"
      ? stored
      : document.documentElement.dataset.theme === "dark"
        ? "dark"
        : "light";
  });
  const [deviceSearch, setDeviceSearch] = useState("");
  const navigate = useNavigate();
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("labguard-theme", theme);
  }, [theme]);
  const current =
    groups.flatMap((g) => g.items).find((i) => location.pathname === i.path) ??
    (location.pathname.startsWith("/devices/")
      ? { label: "Device details", path: "/devices", icon: Laptop }
      : { label: "Workspace", path: "/", icon: Gauge });
  return (
    <div
      className={`min-h-screen ${collapsed ? "lg:[&_.app-sidebar]:w-[76px] lg:[&_.app-main]:ml-[76px]" : ""}`}
    >
      <aside
        className={`app-sidebar fixed inset-y-0 left-0 z-30 flex w-[252px] flex-col bg-slate-950 px-3.5 py-5 text-white shadow-xl transition-all max-[720px]:-translate-x-full ${open ? "max-[720px]:translate-x-0" : ""}`}
      >
        <div className="flex min-h-9 items-center gap-2.5 px-2.5 pb-5">
          <span className="grid h-[34px] w-[34px] place-items-center rounded-xl bg-blue-600 text-xl font-extrabold shadow-lg shadow-blue-500/30">
            L
          </span>
          <div className="sidebar-copy">
            <strong className="block text-[17px]">LabGuard</strong>
            <small className="block text-[9px] tracking-[1.4px] text-slate-400">
              ADMIN CONSOLE
            </small>
          </div>
          <button
            className="ml-auto grid h-8 w-8 place-items-center rounded-md border-0 bg-transparent text-slate-400 hover:bg-white/10 hover:text-white max-[720px]:hidden"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          >
            {collapsed ? (
              <PanelLeftOpen size={17} />
            ) : (
              <PanelLeftClose size={17} />
            )}
          </button>
          <button
            className="ml-auto hidden border-0 bg-transparent text-slate-400 max-[720px]:block"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>
        <div className="mb-5 flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 p-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-slate-700 text-blue-200">
            <Command size={16} />
          </span>
          <span className="sidebar-copy flex-1">
            <strong className="block text-xs">Lab Network</strong>
            <small className="block text-[10px] text-slate-400">
              Institution workspace
            </small>
          </span>
          <ChevronDown size={14} className="sidebar-copy text-slate-400" />
        </div>
        <nav className="flex-1 overflow-y-auto">
          {groups.map((group) => (
            <div className="mb-5" key={group.title}>
              <p className="sidebar-copy mb-1.5 px-2.5 text-[9px] font-bold tracking-[1.2px] text-slate-500">
                {group.title}
              </p>
              {group.items.map((item) => {
                const Icon = item.icon;
                const active =
                  item.path === "/"
                    ? location.pathname === "/"
                    : location.pathname === item.path ||
                      (item.path === "/devices" &&
                        location.pathname.startsWith("/devices/"));
                return (
                  <Link
                    onClick={() => setOpen(false)}
                    className={`mx-0 my-0.5 flex h-9 items-center gap-3 rounded-lg px-2.5 text-xs text-slate-400 transition hover:bg-white/10 hover:text-white ${active ? "bg-slate-800 text-white shadow-[inset_2px_0_#78a9ff]" : ""}`}
                    to={item.path}
                    key={item.path}
                  >
                    <Icon size={17} />
                    <span className="sidebar-copy flex-1">{item.label}</span>
                    {[
                      "/software",
                      "/deployment",
                      "/processes",
                      "/network",
                      "/usb",
                      "/remote-access",
                    ].includes(item.path) && (
                      <i className="h-1 w-1 rounded-full bg-slate-600" />
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="flex items-center gap-2 border-t border-white/10 px-1.5 pt-3">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-slate-700 text-xs font-bold text-blue-200">
            {admin?.username?.slice(0, 1).toUpperCase()}
          </span>
          <span className="sidebar-copy min-w-0 flex-1">
            <strong className="block truncate text-[11px]">
              {admin?.username}
            </strong>
            <small className="block truncate text-[9px] text-slate-400">
              {admin?.role?.replaceAll("_", " ")}
            </small>
          </span>
          <button
            className="grid h-8 w-8 place-items-center rounded-md border-0 bg-transparent text-slate-400 hover:bg-white/10"
            title="Sign out"
            aria-label="Sign out"
            onClick={() => void logout()}
          >
            <X size={16} />
          </button>
        </div>
      </aside>
      {open && (
        <button
          className="fixed inset-0 z-20 hidden bg-slate-950/40 max-[720px]:block"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        />
      )}
      <main className="app-main ml-[252px] flex min-h-screen flex-col bg-[var(--color-bg)] transition-all max-[720px]:ml-0">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-[var(--color-border)] bg-[color-mix(in_srgb,var(--color-surface)_94%,transparent)] px-9 backdrop-blur-xl max-[720px]:px-4">
          <div className="flex items-center gap-3 text-xs">
            <button
              className="hidden border-0 bg-transparent text-[var(--color-muted)] max-[720px]:block"
              onClick={() => setOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={19} />
            </button>
            <span className="text-[var(--color-muted)]">Workspace</span>
            <span className="text-[var(--color-border-strong)]">/</span>
            <span className="font-semibold text-[var(--color-foreground)]">
              {current.label}
            </span>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <form
              className="flex h-9 w-[min(280px,30vw)] items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-2.5 text-[var(--color-muted)] max-[720px]:w-9 max-[720px]:border-transparent max-[720px]:bg-transparent max-[720px]:focus-within:w-[190px]"
              onSubmit={(event) => {
                event.preventDefault();
                navigate(
                  `/devices${deviceSearch.trim() ? `?search=${encodeURIComponent(deviceSearch.trim())}` : ""}`,
                );
              }}
            >
              <Search size={15} />
              <input
                className="w-full border-0 bg-transparent text-[11px] text-[var(--color-foreground)] outline-none placeholder:text-[var(--color-muted)] max-[720px]:hidden max-[720px]:focus-within:block"
                aria-label="Search devices"
                placeholder="Search devices…"
                value={deviceSearch}
                onChange={(event) => setDeviceSearch(event.target.value)}
              />
              <kbd className="text-[9px] text-[var(--color-muted)] max-[720px]:hidden">
                ⌘ K
              </kbd>
            </form>
            <button
              className="grid h-8 w-8 place-items-center rounded-md border-0 bg-transparent text-[var(--color-muted)] hover:bg-[var(--color-surface-subtle)]"
              onClick={() =>
                setTheme((value) => (value === "light" ? "dark" : "light"))
              }
              aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
              title="Toggle theme"
            >
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </button>
            <div className="h-6 w-px bg-[var(--color-border)] max-[720px]:hidden" />
            <button
              className="flex items-center gap-2 border-0 bg-transparent text-[11px] font-semibold text-[var(--color-foreground)]"
              onClick={() => void logout()}
              title="Sign out"
            >
              <span className="grid h-8 w-8 place-items-center rounded-full bg-blue-950 text-xs font-bold text-blue-200">
                {admin?.username?.slice(0, 1).toUpperCase()}
              </span>
              <span className="max-[720px]:hidden">{admin?.username}</span>
              <ChevronDown size={14} className="max-[720px]:hidden" />
            </button>
          </div>
        </header>
        <div className="mx-auto w-full max-w-[1420px] flex-1 px-9 py-9 max-[720px]:px-4 max-[720px]:py-6">
          {children}
        </div>
        <footer className="border-t border-[var(--color-border)] px-9 py-4 text-[10px] text-[var(--color-muted)] max-[720px]:px-4">
          LabGuard Admin Console <span className="px-1">·</span> Live fleet
          operations
        </footer>
      </main>
    </div>
  );
}
function AdminEventBridge() {
  const { admin } = useAuth();
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!admin) return;
    const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
    const stream = new EventSource(`${base}/api/v1/admin/events`, {
      withCredentials: true,
    });
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["statuses"] });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
    };
    const refreshTelemetry = () => {
      void queryClient.invalidateQueries({ queryKey: ["telemetry"] });
      void queryClient.invalidateQueries({ queryKey: ["telemetry-history"] });
      void queryClient.invalidateQueries({ queryKey: ["telemetry-summary"] });
    };
    const refreshSoftware = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as { device_id?: string };
      void queryClient.invalidateQueries({ queryKey: ["software"] });
      void queryClient.invalidateQueries({ queryKey: ["software-summary"] });
      if (data.device_id) {
        void queryClient.invalidateQueries({ queryKey: ["device-software", data.device_id] });
      } else {
        void queryClient.invalidateQueries({ queryKey: ["device-software"] });
      }
    };
    const refreshSoftwareJobs = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as { device_id?: string };
      void queryClient.invalidateQueries({ queryKey: ["software-jobs"] });
      if (data.device_id) void queryClient.invalidateQueries({ queryKey: ["software-jobs", data.device_id] });
    };
    stream.addEventListener("device.status", refresh);
    stream.addEventListener("device.connection", refresh);
    stream.addEventListener("device.telemetry", refreshTelemetry);
    stream.addEventListener("software.inventory", refreshSoftware);
    stream.addEventListener("software.job", refreshSoftwareJobs);
    const deviceDeleted = (event: MessageEvent<string>) => {
      const id = (JSON.parse(event.data) as { device_id: string }).device_id;
      queryClient.setQueryData<Device[]>(["devices"], (current) =>
        current?.filter((device) => device.id !== id),
      );
      queryClient.removeQueries({ queryKey: ["device-status", id] });
      queryClient.removeQueries({ queryKey: ["telemetry", id] });
      queryClient.removeQueries({ queryKey: ["telemetry-history", id] });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      void queryClient.invalidateQueries({ queryKey: ["statuses"] });
      void queryClient.invalidateQueries({ queryKey: ["rooms"] });
      void queryClient.invalidateQueries({ queryKey: ["room-layout"] });
      void queryClient.invalidateQueries({ queryKey: ["telemetry-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["audit"] });
      window.dispatchEvent(
        new CustomEvent("labguard:device-deleted", {
          detail: { deviceId: id },
        }),
      );
    };
    stream.addEventListener("device.deleted", deviceDeleted);
    return () => stream.close();
  }, [admin, queryClient]);
  return null;
}
function RoutedShell() {
  return (
    <>
      <AdminEventBridge />
      <Shell>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/devices/:id" element={<DeviceDetailPage />} />
          <Route path="/rooms" element={<RoomsPage />} />
          <Route path="/enrollment" element={<EnrollmentPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route
            path="/software"
            element={<SoftwarePage />}
          />
          <Route
            path="/deployment"
            element={<SoftwareDeploymentPage />}
          />
          <Route
            path="/processes"
            element={<ProcessMonitoringPage />}
          />
          <Route
            path="/network"
            element={<Placeholder title="Network Monitoring" />}
          />
          <Route path="/usb" element={<Placeholder title="USB Monitoring" />} />
          <Route
            path="/remote-access"
            element={<Placeholder title="Remote Access" />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Shell>
    </>
  );
}
export function App() {
  const { admin } = useAuth();
  return (
    <Routes>
      <Route
        path="/login"
        element={admin ? <Navigate to="/" replace /> : <LoginPage />}
      />
      <Route
        path="*"
        element={
          <Protected>
            <RoutedShell />
          </Protected>
        }
      />
    </Routes>
  );
}
