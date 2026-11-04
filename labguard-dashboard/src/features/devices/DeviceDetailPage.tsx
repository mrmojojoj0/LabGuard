import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Radio, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { devicesApi } from './api'
import { ComingSoon, PageHeader, Panel, PanelTitle, QueryError, Skeleton, StatusBadge } from '../../components/ui'

const tabs = ['Overview', 'Hardware', 'Software', 'Processes', 'Network', 'Remote Access', 'Activity']
export function DeviceDetailPage() {
  const { id = '' } = useParams(); const [tab, setTab] = useState('Overview')
  const devices = useQuery({ queryKey: ['devices'], queryFn: devicesApi.list }); const statuses = useQuery({ queryKey: ['device-status', id], queryFn: () => devicesApi.status(id), refetchInterval: 20_000 })
  const device = devices.data?.find(d => d.id === id)
  return <><div className="breadcrumbs"><Link to="/devices">Devices</Link><ChevronRight size={14}/><span>{device?.assigned_name || device?.hostname || 'Device details'}</span></div>
    {devices.isError && <QueryError error={devices.error}/>} {statuses.isError && <QueryError error={statuses.error}/>}
    {devices.isLoading ? <Skeleton rows={2}/> : device ? <>
      <PageHeader eyebrow="DEVICE PROFILE" title={device.assigned_name || device.hostname} description={<span className="mono">{device.id}</span>} action={<StatusBadge value={statuses.data?.agent_state ?? 'UNKNOWN'}/>}/>
      <div className="tab-list" role="tablist">{tabs.map(item => <button role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{item}{!['Overview'].includes(item) && <span className="tab-soon">SOON</span>}</button>)}</div>
      {tab === 'Overview' ? <div className="detail-grid"><Panel><PanelTitle>Device information</PanelTitle><div className="detail-list"><div><span>Hostname</span><strong>{device.hostname}</strong></div><div><span>Assigned name</span><strong>{device.assigned_name ?? 'Not assigned'}</strong></div><div><span>Device UUID</span><strong className="mono">{device.id}</strong></div><div><span>Enrollment</span><strong>{device.enrollment_state}</strong></div><div><span>Agent version</span><strong>{device.agent_version ?? 'Unavailable'}</strong></div><div><span>Enabled</span><strong>{device.enabled ? 'Yes' : 'No'}</strong></div></div></Panel><Panel><PanelTitle>Connection</PanelTitle><div className="connection-state"><span className="connection-icon"><Radio size={20}/></span><div><StatusBadge value={statuses.data?.agent_state ?? 'UNKNOWN'}/><p>{statuses.data?.network_state ? `Network reachability: ${statuses.data.network_state}` : 'Network status unavailable'}</p></div></div><div className="detail-list"><div><span>Last heartbeat</span><strong>{statuses.data?.last_heartbeat_at ? new Date(statuses.data.last_heartbeat_at).toLocaleString() : 'No heartbeat recorded'}</strong></div><div><span>Last seen</span><strong>{statuses.data?.last_seen_at ? new Date(statuses.data.last_seen_at).toLocaleString() : 'Never connected'}</strong></div><div><span>Status changed</span><strong>{statuses.data?.changed_at ? new Date(statuses.data.changed_at).toLocaleString() : '—'}</strong></div></div><div className="info-note"><ShieldCheck size={15}/> Status is based on authenticated server heartbeat receipt.</div></Panel></div> : <ComingSoon title={`${tab} data isn’t available yet`} description="The current server API does not provide this device data. This section will become active when the corresponding backend endpoint is implemented."/>}
    </> : !devices.isLoading && <Panel><div className="empty-inline">Device not found in the current server registry.</div></Panel>}
  </>
}
