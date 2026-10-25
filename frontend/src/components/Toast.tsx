import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "../lib/utils";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  text: string;
}

type PushFn = (kind: ToastKind, text: string) => void;
const ToastCtx = createContext<PushFn>(() => {});

let seq = 0;

const ICONS: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="h-4.5 w-4.5 text-emerald-400" />,
  error: <XCircle className="h-4.5 w-4.5 text-rose-400" />,
  info: <Info className="h-4.5 w-4.5 text-violet-300" />,
};

export function useToast() {
  return useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback<PushFn>((kind, text) => {
    const id = ++seq;
    setItems((prev) => [...prev.slice(-2), { id, kind, text }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 3600);
  }, []);

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed left-1/2 top-6 z-[100] flex w-full max-w-md -translate-x-1/2 flex-col items-center gap-2 px-4">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: -14, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 28 }}
              className={cn(
                "glass-card pointer-events-auto flex w-auto max-w-full items-center gap-2.5 rounded-full px-4 py-2.5 text-sm text-slate-100 shadow-xl",
              )}
            >
              {ICONS[t.kind]}
              <span className="leading-snug">{t.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}
