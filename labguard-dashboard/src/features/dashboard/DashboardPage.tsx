import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Monitor, Signal, SignalLow, SignalZero, UserRoundCheck, Activity, Clock3 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { devicesApi } from '../devices/api'
import { enrollmentApi } from '../enrollment/api'
import { auditApi } from '../audit/api'
import { PageHeader, Panel, PanelTitle, QueryError, Skeleton, StatusBadge } from '../../components/ui'
import type { AuditEvent } from '../../lib/types'

export function DashboardPage() {
  const devices = useQuery({ queryKey: ['devices'], queryFn: devicesApi.list })
  const pending = useQuery({ queryKey: ['enrollment'], queryFn: enrollmentApi.pending })
  const audit = useQuery({ queryKey: ['audit'], queryFn: auditApi.list })
  const statuses = useQuery({ queryKey: ['statuses', devices.data?.map(d => d.id)], queryFn: () => devicesApi.statuses(devices.data ?? []), enabled: !!devices.data, refetchInterval: 20_000 })
  const registered = devices.data?.filter(device => device.enrollment_state === 'APPROVED') ?? []
  const registeredStatuses = statuses.data?.filter(s => s && registered.some(device => device.id === s.device_id)) ?? []
  const states = registeredStatuses.map(s => s!.agent_state)
  const counts = { ONLINE: states.filter(s => s === 'ONLINE').length, DELAYED: states.filter(s => s === 'DELAYED').length, OFFLINE: states.filter(s => s === 'OFFLINE').length }
  const cards = [
    { label: 'Registered devices', value: registered.length, icon: Monitor, tone: 'blue', note: 'Approved endpoints' },
    { label: 'Online', value: counts.ONLINE, icon: Signal, tone: 'green', note: 'Active heartbeat' },
    { label: 'Delayed', value: counts.DELAYED, icon: SignalLow, tone: 'amber', note: 'Heartbeat overdue' },
    { label: 'Offline', value: counts.OFFLINE, icon: SignalZero, tone: 'slate', note: 'No recent heartbeat' },
    { label: 'Pending enrollment', value: pending.data?.length, icon: UserRoundCheck, tone: 'violet', note: 'Awaiting review' },
  ]
  return <><PageHeader eyebrow="FLEET OVERVIEW" title="Good morning" description="Here’s what’s happening across your managed labs." action={<span className="synced"><span className="live-dot"/> Live data · refreshes every 20 sec</span>} />
    {(devices.isError || pending.isError || audit.isError) && <QueryError error={devices.error ?? pending.error ?? audit.error} />}
    <div className="metric-grid">{cards.map(card => { const Icon = card.icon; const loading = card.label === 'Registered devices' ? devices.isLoading : card.label === 'Pending enrollment' ? pending.isLoading : statuses.isLoading; return <Panel className="metric-card" key={card.label}><div className={`metric-icon ${card.tone}`}><Icon size={19}/></div><p>{card.label}</p><strong>{loading ? '—' : card.value ?? 0}</strong><small>{card.note}</small></Panel> })}</div>
    <div className="content-grid"><Panel><PanelTitle aside={<Link className="text-link" to="/devices">View all <ArrowUpRight size={14}/></Link>}>Device activity</PanelTitle>
      {devices.isLoading ? <Skeleton/> : registered.length ? <div className="activity-list">{[...registered].sort((a, b) => (new Date(statuses.data?.find(s => s?.device_id === b.id)?.last_seen_at ?? 0).getTime() || 0) - (new Date(statuses.data?.find(s => s?.device_id === a.id)?.last_seen_at ?? 0).getTime() || 0)).slice(0, 6).map(device => { const status = statuses.data?.find(s => s?.device_id === device.id); return <Link to={`/devices/${device.id}`} className="activity-row" key={device.id}><span className="device-avatar"><Monitor size={17}/></span><div className="activity-main"><strong>{device.assigned_name || device.hostname}</strong><span>{status?.last_seen_at ? `Last seen ${new Date(status.last_seen_at).toLocaleString()}` : 'Never connected'} · {device.agent_version ? `Agent ${device.agent_version}` : 'Version unavailable'}</span></div><StatusBadge value={status?.agent_state ?? 'UNKNOWN'}/></Link> })}</div> : <div className="empty-inline">No approved devices yet.</div>}</Panel>
      <Panel><PanelTitle aside={<Link className="text-link" to="/audit">View all <ArrowUpRight size={14}/></Link>}>Recent audit activity</PanelTitle>
        {audit.isLoading ? <Skeleton rows={4}/> : audit.data?.length ? <div className="audit-list">{audit.data.slice(0, 6).map((item: AuditEvent) => <div className="audit-row" key={item.id}><span className="audit-mark"><Activity size={15}/></span><div><strong>{item.action.replaceAll('.', ' ')}</strong><span>{item.target_type}{item.target_id ? ` · ${item.target_id.slice(0, 8)}` : ''}</span></div><time><Clock3 size={12}/>{new Date(item.occurred_at).toLocaleString()}</time></div>)}</div> : <div className="empty-inline">No audit activity available.</div>}</Panel></div>
    {statuses.isError && <p className="inline-note">Some device status records could not be loaded. Counts include only available server status responses.</p>}
  </>
}
