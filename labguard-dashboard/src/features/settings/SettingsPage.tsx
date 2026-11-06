import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { Button, PageHeader, Panel, PanelTitle } from "../../components/ui";
export function SettingsPage() {
  const { admin, logout } = useAuth();
  return (
    <>
      <PageHeader
        eyebrow="ADMINISTRATION"
        title="Settings"
        description="Administrator account and dashboard connection settings."
      />
      <div className="grid gap-4 min-[981px]:grid-cols-2">
        <Panel>
          <PanelTitle>Administrator account</PanelTitle>
          <div className="my-4 flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
              <UserRound size={21} />
            </span>
            <div>
              <strong className="block text-xs text-[var(--color-foreground)]">
                {admin?.username}
              </strong>
              <span className="block text-[10px] text-[var(--color-muted)]">
                {admin?.role?.replaceAll("_", " ")}
              </span>
            </div>
            <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-[var(--color-success)]">
              <ShieldCheck size={15} /> Active
            </span>
          </div>
          <div className="grid">
            <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5 text-[10px]">
              <span className="text-[var(--color-muted)]">Account ID</span>
              <strong className="font-mono text-[9px] text-[var(--color-foreground)]">
                {admin?.id}
              </strong>
            </div>
            <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5 text-[10px]">
              <span className="text-[var(--color-muted)]">Role</span>
              <strong className="text-[var(--color-foreground)]">
                {admin?.role}
              </strong>
            </div>
            <div className="flex justify-between gap-3 py-2.5 text-[10px]">
              <span className="text-[var(--color-muted)]">Authentication</span>
              <strong className="text-right text-[var(--color-foreground)]">
                Server-managed session cookie
              </strong>
            </div>
          </div>
          <Button
            className="mt-4 border-red-200 text-red-700 dark:border-red-900 dark:text-red-300"
            onClick={() => void logout()}
          >
            <LogOut size={16} /> Sign out
          </Button>
        </Panel>
        <Panel>
          <PanelTitle>Application configuration</PanelTitle>
          <div className="grid">
            <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5 text-[10px]">
              <span className="text-[var(--color-muted)]">API base URL</span>
              <strong className="text-right text-[var(--color-foreground)]">
                {import.meta.env.VITE_API_BASE_URL || "Same origin"}
              </strong>
            </div>
            <div className="flex justify-between gap-3 border-b border-[var(--color-border)] py-2.5 text-[10px]">
              <span className="text-[var(--color-muted)]">
                Dashboard version
              </span>
              <strong className="text-[var(--color-foreground)]">
                0.1.0 · Phase 1
              </strong>
            </div>
            <div className="flex justify-between gap-3 py-2.5 text-[10px]">
              <span className="text-[var(--color-muted)]">Live updates</span>
              <strong className="text-[var(--color-foreground)]">
                Polling every 20 seconds
              </strong>
            </div>
          </div>
          <p className="mt-3 text-[9px] leading-relaxed text-[var(--color-muted)]">
            The current server provides an agent-only WebSocket. Administrator
            event streaming requires a separate backend endpoint.
          </p>
        </Panel>
      </div>
    </>
  );
}
