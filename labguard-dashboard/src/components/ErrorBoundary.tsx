import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
interface Props {
  children: ReactNode;
}
interface State {
  failed: boolean;
}
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };
  static getDerivedStateFromError(): State {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard rendering error", error, info.componentStack);
  }
  render() {
    if (this.state.failed)
      return (
        <main className="flex min-h-screen flex-col items-center justify-center gap-3 bg-[var(--color-bg)] p-6 text-center text-[var(--color-muted)]">
          <AlertTriangle size={24} className="text-[var(--color-danger)]" />
          <h1 className="text-xl font-bold text-[var(--color-foreground)]">
            Something went wrong
          </h1>
          <p className="text-sm">
            This page could not be displayed. Reload to try again.
          </p>
          <button
            className="rounded-lg bg-[var(--color-primary)] px-3 py-2 text-xs font-semibold text-white"
            onClick={() => location.reload()}
          >
            Reload dashboard
          </button>
        </main>
      );
    return this.props.children;
  }
}
