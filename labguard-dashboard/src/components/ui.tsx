import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { AlertCircle, LoaderCircle } from 'lucide-react'
import { cva } from 'class-variance-authority'
import { ApiError } from '../lib/api'
import { cn } from '../lib/utils'

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: ReactNode; action?: ReactNode }) { return <div className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <div className="muted">{description}</div>}</div>{action}</div> }
const buttonStyles = cva('button', { variants: { intent: { primary: 'primary', danger: 'danger', success: 'success' } } })
export function Button({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) { return <button className={cn(buttonStyles(), className)} {...props} /> }
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) { return <section className={`panel ${className}`}>{children}</section> }
export function PanelTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) { return <div className="panel-title"><h2>{children}</h2>{aside}</div> }
export function StatusBadge({ value }: { value: string }) { const cls = value.toLowerCase().replaceAll('_', '-'); return <span className={`status-badge ${cls}`}><span className="status-dot" />{value.replaceAll('_', ' ')}</span> }
export function Loading({ label = 'Loading data…' }: { label?: string }) { return <div className="loading"><LoaderCircle size={18} className="spin" />{label}</div> }
export function QueryError({ error }: { error: unknown }) { return <div className="query-error"><AlertCircle size={18}/><span>{error instanceof ApiError ? error.message : 'This information could not be loaded.'}</span><small>Check the API base URL and server connection.</small></div> }
export function Empty({ title, detail }: { title: string; detail: string }) { return <div className="empty-state"><span className="empty-icon">○</span><strong>{title}</strong><span>{detail}</span></div> }
export function Skeleton({ rows = 3 }: { rows?: number }) { return <div className="skeleton-stack">{Array.from({ length: rows }, (_, i) => <div className="skeleton-row" key={i} />)}</div> }
export function ComingSoon({ title, description }: { title: string; description: string }) { return <div className="coming-soon"><span className="soon-pill">COMING SOON</span><h2>{title}</h2><p>{description}</p></div> }
