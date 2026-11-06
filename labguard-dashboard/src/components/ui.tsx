import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { cva } from "class-variance-authority";
import { ApiError } from "../lib/api";
import { cn } from "../lib/utils";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-end justify-between gap-5 max-[680px]:flex-col max-[680px]:items-start">
      <div>
        {eyebrow && (
          <p className="text-[9px] font-bold tracking-[1.4px] text-[var(--color-muted)]">
            {eyebrow}
          </p>
        )}
        <h1 className="my-1 text-[26px] font-bold tracking-tight text-[var(--color-foreground)]">
          {title}
        </h1>
        {description && (
          <div className="text-xs leading-relaxed text-[var(--color-muted)]">
            {description}
          </div>
        )}
      </div>
      {action}
    </div>
  );
}
const buttonStyles = cva(
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2 text-[10px] font-semibold text-[var(--color-muted)] transition hover:-translate-y-px hover:bg-[var(--color-surface-subtle)] disabled:cursor-not-allowed disabled:opacity-55",
  {
    variants: {
      intent: {
        primary:
          "bg-[var(--color-primary)] text-white border-[var(--color-primary)]",
        danger:
          "border-red-200 text-red-700 dark:border-red-900 dark:text-red-300",
        success:
          "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300",
      },
    },
  },
);
export function Button({
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn(buttonStyles(), className)} {...props} />;
}
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-sm ${className}`}
    >
      {children}
    </section>
  );
}
export function PanelTitle({
  children,
  aside,
}: {
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] pb-3.5">
      <h2 className="m-0 text-[13px] font-bold text-[var(--color-foreground)]">
        {children}
      </h2>
      {aside}
    </div>
  );
}
export function StatusBadge({ value }: { value: string }) {
  const cls = value.toLowerCase().replaceAll("_", "-");
  const tone = ["online", "success"].includes(cls)
    ? "bg-[var(--color-success-soft)] text-[var(--color-success)]"
    : cls === "delayed"
      ? "bg-[var(--color-warning-soft)] text-[var(--color-warning)]"
      : ["offline", "rejected", "error"].includes(cls)
        ? "bg-[var(--color-danger-soft)] text-[var(--color-danger)]"
        : cls === "pending"
          ? "bg-[var(--color-primary-soft)] text-[var(--color-primary)]"
          : "bg-[var(--color-surface-subtle)] text-[var(--color-muted)]";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-1 text-[9px] font-semibold capitalize ${tone}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function Loading({ label = "Loading data…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-9 text-[11px] text-[var(--color-muted)]">
      <LoaderCircle size={18} className="animate-spin" />
      {label}
    </div>
  );
}
export function QueryError({ error }: { error: unknown }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[11px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
      <AlertCircle size={18} />
      <span>
        {error instanceof ApiError
          ? error.message
          : "This information could not be loaded."}
      </span>
      <small className="basis-full pl-6 text-[9px] text-red-500">
        Check the API base URL and server connection.
      </small>
    </div>
  );
}
export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex min-h-[210px] flex-col items-center justify-center gap-2 text-center">
      <span className="grid h-11 w-11 place-items-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-subtle)] text-2xl text-[var(--color-muted)]">
        ○
      </span>
      <strong className="text-xs text-[var(--color-foreground)]">
        {title}
      </strong>
      <span className="text-[10px] text-[var(--color-muted)]">{detail}</span>
    </div>
  );
}
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="py-3">
      {Array.from({ length: rows }, (_, i) => (
        <div
          className="my-1.5 h-10 animate-[shimmer_1.5s_infinite] rounded-md bg-[linear-gradient(90deg,var(--color-surface-subtle),var(--color-border),var(--color-surface-subtle))] bg-[length:200%_100%]"
          key={i}
        />
      ))}
    </div>
  );
}
export function ComingSoon({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-[270px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface-subtle)] p-6 text-center">
      <span className="rounded-full bg-[var(--color-primary-soft)] px-2 py-1 text-[8px] font-bold tracking-[1px] text-[var(--color-primary)]">
        COMING SOON
      </span>
      <h2 className="my-3 text-[17px] font-bold text-[var(--color-foreground)]">
        {title}
      </h2>
      <p className="max-w-[440px] text-[11px] leading-relaxed text-[var(--color-muted)]">
        {description}
      </p>
    </div>
  );
}
