import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes, useLocation, Link } from 'react-router-dom'
import { Activity, ChevronDown, Command, Cpu, FileClock, Gauge, Grid2X2, Headphones, Laptop, Menu, Network, Package, Settings, Usb, UserRoundCheck, X } from 'lucide-react'
import { LoginPage, useAuth } from '../features/auth/AuthProvider'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { DevicesPage } from '../features/devices/DevicesPage'
import { DeviceDetailPage } from '../features/devices/DeviceDetailPage'
import { RoomsPage } from '../features/rooms/RoomsPage'
import { EnrollmentPage } from '../features/enrollment/EnrollmentPage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { AuditPage } from '../features/audit/AuditPage'
import { ComingSoon } from '../components/ui'
import type { Device } from '../lib/types'

type Nav = { label: string; path: string; icon: ComponentType<{ size?: number }> }
const groups: { title: string; items: Nav[] }[] = [
  { title: 'WORKSPACE', items: [{ label: 'Overview', path: '/', icon: Gauge }, { label: 'Rooms & Labs', path: '/rooms', icon: Grid2X2 }, { label: 'Devices', path: '/devices', icon: Laptop }, { label: 'Enrollment Requests', path: '/enrollment', icon: UserRoundCheck }] },
  { title: 'MONITORING', items: [{ label: 'Software Inventory', path: '/software', icon: Package }, { label: 'Software Deployment', path: '/deployment', icon: Cpu }, { label: 'Process Monitoring', path: '/processes', icon: Activity }, { label: 'Network Monitoring', path: '/network', icon: Network }, { label: 'USB Monitoring', path: '/usb', icon: Usb }, { label: 'Remote Access', path: '/remote-access', icon: Headphones }] },
  { title: 'SYSTEM', items: [{ label: 'Audit Logs', path: '/audit', icon: FileClock }, { label: 'Settings', path: '/settings', icon: Settings }] },
]
function Protected({ children }: { children: React.ReactNode }) { const { admin, ready } = useAuth(); if (!ready) return null; return admin ? <>{children}</> : <Navigate to="/login" replace/> }
function Placeholder({ title }: { title: string }) { return <><div className="eyebrow">MONITORING</div><h1 className="standalone-title">{title}</h1><ComingSoon title={`${title} is planned`} description="The current LabGuard server API does not provide this capability. This page will be enabled when backend support is available."/></> }
function Shell({ children }: { children: ReactNode }) {
  const { admin, logout } = useAuth(); const location = useLocation(); const [open, setOpen] = useState(false)
  const current = groups.flatMap(g => g.items).find(i => location.pathname === i.path) ?? (location.pathname.startsWith('/devices/') ? { label: 'Device details', path: '/devices', icon: Laptop } : { label: 'Workspace', path: '/', icon: Gauge })
  return <div className="app-shell"><aside className={`sidebar ${open ? 'sidebar-open' : ''}`}><div className="sidebar-brand"><span className="brand-mark">L</span><div><strong>LabGuard</strong><small>ADMIN CONSOLE</small></div><button className="mobile-close" onClick={() => setOpen(false)}><X size={18}/></button></div><div className="workspace-select"><span className="workspace-icon"><Command size={16}/></span><span><strong>Lab Network</strong><small>Institution workspace</small></span><ChevronDown size={14}/></div><nav>{groups.map(group => <div className="nav-group" key={group.title}><p>{group.title}</p>{group.items.map(item => { const Icon = item.icon; const active = item.path === '/' ? location.pathname === '/' : location.pathname === item.path || (item.path === '/devices' && location.pathname.startsWith('/devices/')); return <Link onClick={() => setOpen(false)} className={`nav-link ${active ? 'active' : ''}`} to={item.path} key={item.path}><Icon size={17}/><span>{item.label}</span>{['/software','/deployment','/processes','/network','/usb','/remote-access'].includes(item.path) && <i className="nav-soon"/>}</Link> })}</div>)}</nav><div className="sidebar-footer"><span className="sidebar-avatar">{admin?.username?.slice(0,1).toUpperCase()}</span><span className="sidebar-user"><strong>{admin?.username}</strong><small>{admin?.role?.replaceAll('_',' ')}</small></span><button className="icon-button logout-mini" title="Sign out" onClick={() => void logout()}><X size={16}/></button></div></aside>
    {open && <button className="mobile-scrim" onClick={() => setOpen(false)} aria-label="Close navigation"/>}<main className="main-shell"><header className="topbar"><div className="topbar-left"><button className="menu-toggle" onClick={() => setOpen(true)}><Menu size={19}/></button><span className="breadcrumb-root">Workspace</span><span className="crumb-sep">/</span><span className="breadcrumb-current">{current.label}</span></div><div className="topbar-actions"><div className="topbar-divider"/><button className="account-button" onClick={() => void logout()} title="Sign out"><span className="sidebar-avatar">{admin?.username?.slice(0,1).toUpperCase()}</span><span>{admin?.username}</span><ChevronDown size={14}/></button></div></header><div className="main-content">{children}</div><footer>LabGuard Admin Console <span>·</span> Phase 1 foundation</footer></main></div>
}
function AdminEventBridge() {
  const { admin } = useAuth()
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!admin) return
    const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
    const stream = new EventSource(`${base}/api/v1/admin/events`, { withCredentials: true })
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ['statuses'] })
      void queryClient.invalidateQueries({ queryKey: ['devices'] })
    }
    const refreshTelemetry = () => {
      void queryClient.invalidateQueries({ queryKey: ['telemetry'] })
      void queryClient.invalidateQueries({ queryKey: ['telemetry-history'] })
      void queryClient.invalidateQueries({ queryKey: ['telemetry-summary'] })
    }
    stream.addEventListener('device.status', refresh)
    stream.addEventListener('device.connection', refresh)
    stream.addEventListener('device.telemetry', refreshTelemetry)
    const deviceDeleted = (event: MessageEvent<string>) => {
      const id = (JSON.parse(event.data) as { device_id: string }).device_id
      queryClient.setQueryData<Device[]>(['devices'], current => current?.filter(device => device.id !== id))
      queryClient.removeQueries({ queryKey: ['device-status', id] })
      queryClient.removeQueries({ queryKey: ['telemetry', id] })
      queryClient.removeQueries({ queryKey: ['telemetry-history', id] })
      void queryClient.invalidateQueries({ queryKey: ['devices'] })
      void queryClient.invalidateQueries({ queryKey: ['statuses'] })
      void queryClient.invalidateQueries({ queryKey: ['rooms'] })
      void queryClient.invalidateQueries({ queryKey: ['room-layout'] })
      void queryClient.invalidateQueries({ queryKey: ['telemetry-summary'] })
      void queryClient.invalidateQueries({ queryKey: ['audit'] })
      window.dispatchEvent(new CustomEvent('labguard:device-deleted', { detail: { deviceId: id } }))
    }
    stream.addEventListener('device.deleted', deviceDeleted)
    return () => stream.close()
  }, [admin, queryClient])
  return null
}
function RoutedShell() { return <><AdminEventBridge/><Shell><Routes><Route path="/" element={<DashboardPage/>}/><Route path="/devices" element={<DevicesPage/>}/><Route path="/devices/:id" element={<DeviceDetailPage/>}/><Route path="/rooms" element={<RoomsPage/>}/><Route path="/enrollment" element={<EnrollmentPage/>}/><Route path="/settings" element={<SettingsPage/>}/><Route path="/audit" element={<AuditPage/>}/><Route path="/software" element={<Placeholder title="Software Inventory"/>}/><Route path="/deployment" element={<Placeholder title="Software Deployment"/>}/><Route path="/processes" element={<Placeholder title="Process Monitoring"/>}/><Route path="/network" element={<Placeholder title="Network Monitoring"/>}/><Route path="/usb" element={<Placeholder title="USB Monitoring"/>}/><Route path="/remote-access" element={<Placeholder title="Remote Access"/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Routes></Shell></> }
export function App() { const { admin } = useAuth(); return <Routes><Route path="/login" element={admin ? <Navigate to="/" replace/> : <LoginPage/>}/><Route path="*" element={<Protected><RoutedShell/></Protected>}/></Routes> }
