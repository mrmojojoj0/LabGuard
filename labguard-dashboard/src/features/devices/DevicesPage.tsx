import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Monitor, Search, SlidersHorizontal } from 'lucide-react'
import { devicesApi } from './api'
import { PageHeader, Panel, QueryError, Skeleton, StatusBadge, Empty } from '../../components/ui'
import { Link } from 'react-router-dom'

export function DevicesPage() {
  const devices = useQuery({ queryKey: ['devices'], queryFn: devicesApi.list })
  const statuses = useQuery({ queryKey: ['statuses', devices.data?.map(d => d.id)], queryFn: () => devicesApi.statuses(devices.data ?? []), enabled: !!devices.data, refetchInterval: false })
  const [search, setSearch] = useState(''); const [filter, setFilter] = useState('ALL'); const [page, setPage] = useState(1); const pageSize = 10
  const filtered = useMemo(() => (devices.data ?? []).filter(d => {
    const status = statuses.data?.find(s => s?.device_id === d.id)?.agent_state ?? 'UNKNOWN'
    const text = `${d.assigned_name ?? ''} ${d.hostname} ${d.id}`.toLowerCase()
    return text.includes(search.toLowerCase()) && (filter === 'ALL' || status === filter)
  }), [devices.data, statuses.data, search, filter])
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize)
  return <><PageHeader eyebrow="FLEET MANAGEMENT" title="Devices" description="Browse registered endpoints and their latest server-reported status." action={<span className="count-pill"><Monitor size={15}/>{devices.data?.length ?? 0} devices</span>}/>
    {devices.isError && <QueryError error={devices.error}/>}{statuses.isError && <div className="alert subtle">Some status requests failed. Affected devices show UNKNOWN.</div>}
    <Panel><div className="table-toolbar"><label className="search-box"><Search size={17}/><input placeholder="Search name, hostname, or UUID…" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }}/></label><label className="filter-select"><SlidersHorizontal size={16}/><select value={filter} onChange={e => { setFilter(e.target.value); setPage(1) }}><option value="ALL">All statuses</option><option>ONLINE</option><option>DELAYED</option><option>OFFLINE</option><option>NEVER_CONNECTED</option><option>UNKNOWN</option></select></label></div>
      {devices.isLoading ? <Skeleton rows={7}/> : rows.length ? <div className="table-wrap"><table><thead><tr><th>Device</th><th>Hostname</th><th>Device UUID</th><th>Status</th><th>Connection</th><th>Last seen</th><th>Agent</th><th/></tr></thead><tbody>{rows.map(device => { const status = statuses.data?.find(s => s?.device_id === device.id); return <tr key={device.id}><td><Link className="device-cell" to={`/devices/${device.id}`}><span className="device-avatar"><Monitor size={16}/></span><span><strong>{device.assigned_name || device.hostname}</strong><small>{device.enrollment_state}</small></span></Link></td><td>{device.hostname}</td><td className="mono">{device.id}</td><td><StatusBadge value={status?.agent_state ?? 'UNKNOWN'}/></td><td>{status ? (status.connected ? 'Connected' : 'Disconnected') : '—'}</td><td>{status?.last_seen_at ? new Date(status.last_seen_at).toLocaleString() : '—'}</td><td>{device.agent_version ?? '—'}</td><td><Link className="row-link" to={`/devices/${device.id}`} aria-label="View details">→</Link></td></tr> })}</tbody></table></div> : <Empty title={search || filter !== 'ALL' ? 'No matching devices' : 'No devices registered'} detail={search || filter !== 'ALL' ? 'Try changing your search or status filter.' : 'Approved devices will appear here when the server has registered them.'}/ >}
      {!!filtered.length && <div className="pagination"><span>Showing {Math.min((page - 1) * pageSize + 1, filtered.length)}–{Math.min(page * pageSize, filtered.length)} of {filtered.length}</span><div><button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button disabled={page * pageSize >= filtered.length} onClick={() => setPage(page + 1)}>Next</button></div></div>}
    </Panel></>
}
