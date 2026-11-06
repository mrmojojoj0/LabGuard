import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, X } from "lucide-react";
import { cn } from "../lib/utils";
type ToastItem = { id: number; message: string; tone: "success" | "error" };
const ToastContext = createContext<
  (message: string, tone?: ToastItem["tone"]) => void
>(() => undefined);
export const useToast = () => useContext(ToastContext);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback(
    (message: string, tone: ToastItem["tone"] = "success") => {
      const id = Date.now() + Math.random();
      setItems((current) => [...current, { id, message, tone }]);
      window.setTimeout(
        () => setItems((current) => current.filter((item) => item.id !== id)),
        4500,
      );
    },
    [],
  );
  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div
        className="fixed right-4 top-4 z-[200] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2"
        aria-live="polite"
      >
        {items.map((item) => (
          <div
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2.5 text-xs shadow-lg",
              item.tone === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300"
                : "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300",
            )}
            role="status"
            key={item.id}
          >
            <CheckCircle2 size={17} />
            <span className="flex-1">{item.message}</span>
            <button
              className="border-0 bg-transparent text-inherit"
              aria-label="Dismiss notification"
              onClick={() =>
                setItems((current) => current.filter((x) => x.id !== item.id))
              }
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
