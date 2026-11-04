import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import { cn } from '../lib/utils'
type ToastItem = { id: number; message: string; tone: 'success' | 'error' }
const ToastContext = createContext<(message: string, tone?: ToastItem['tone']) => void>(() => undefined)
export const useToast = () => useContext(ToastContext)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const toast = useCallback((message: string, tone: ToastItem['tone'] = 'success') => { const id = Date.now() + Math.random(); setItems(current => [...current, { id, message, tone }]); window.setTimeout(() => setItems(current => current.filter(item => item.id !== id)), 4500) }, [])
  return <ToastContext.Provider value={toast}>{children}<div className="toast-stack" aria-live="polite">{items.map(item => <div className={cn('toast', item.tone)} role="status" key={item.id}><CheckCircle2 size={17}/><span>{item.message}</span><button aria-label="Dismiss notification" onClick={() => setItems(current => current.filter(x => x.id !== item.id))}><X size={15}/></button></div>)}</div></ToastContext.Provider>
}
