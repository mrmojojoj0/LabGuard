import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Radio, ShieldCheck, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { devicesApi } from './api'
import { SystemTelemetry } from './SystemTelemetry'
import { Button, ComingSoon, PageHeader, Panel, PanelTitle, QueryError, Skeleton, StatusBadge } from '../../components/ui'
import { useAuth } from '../auth/AuthProvider'
import { canManageLabs } from '../auth/api'
import { useToast } from '../../components/Toast'

const tabs = ['Overview', 'Hardware', 'Software', 'Processes', 'Network', 'Remote Access', 'Activity']
export function DeviceDetailPage() {
  const { id = '' } = useParams(); const [tab, setTab] = useState('Overview'); const [confirmDelete, setConfirmDelete] = useState(false)
  const { admin } = useAuth(); const toast = useToast(); const navigate = useNavigate(); const qc = useQueryClient()
  const devices = useQuery({ queryKey: ['devices'], queryFn: devicesApi.list }); const statuses = useQuery({ queryKey: ['device-status', id], queryFn: () => devicesApi.status(id), refetchInterval: 20_000 })
  const device = devices.data?.find(d => d.id === id)
  const deleteDevice = useMutation({
    mutationFn: () => devicesApi.remove(id),
    onSuccess: async () => {
      qc.setQueryData(['devices'], (current: typeof devices.data) => current?.filter(item => item.id !== id))
      qc.removeQueries({ queryKey: ['device-status', id] }); qc.removeQueries({ queryKey: ['telemetry', id] }); qc.removeQueries({ queryKey: ['telemetry-history', id] })
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['devices'] }), qc.invalidateQueries({ queryKey: ['rooms'] }),
        qc.invalidateQueries({ queryKey: ['room-layout'] }), qc.invalidateQueries({ queryKey: ['statuses'] }),
        qc.invalidateQueries({ queryKey: ['telemetry-summary'] }), qc.invalidateQueries({ queryKey: ['audit'] }),
      ])
      setConfirmDelete(false); toast('Device permanently deleted. Enroll it again before it can reconnect.'); navigate('/devices', { replace: true })
    },
    onError: (error: Error) => toast(`Device was not deleted. ${error.message}`, 'error'),
  })
  useEffect(() => {
    const onDeleted = (event: Event) => {
      if ((event as CustomEvent<{ deviceId: string }>).detail?.deviceId !== id) return
      navigate('/devices', { replace: true })
    }
    window.addEventListener('labguard:device-deleted', onDeleted)
    return () => window.removeEventListener('labguard:device-deleted', onDeleted)
  }, [id, navigate])
  return <><div className="breadcrumbs"><Link to="/devices">Devices</Link><ChevronRight size={14}/><span>{device?.assigned_name || device?.hostname || 'Device details'}</span></div>
    {devices.isError && <QueryError error={devices.error}/>} {statuses.isError && <QueryError error={statuses.error}/>}
    {devices.isLoading ? <Skeleton rows={2}/> : device ? <>
      <PageHeader eyebrow="DEVICE PROFILE" title={device.assigned_name || device.hostname} description={<span className="mono">{device.id}</span>} action={<div className="inline-actions"><StatusBadge value={statuses.data?.agent_state ?? 'UNKNOWN'}/>{canManageLabs(admin?.role) && <Button className="danger" onClick={() => setConfirmDelete(true)}><Trash2 size={15}/> Delete device</Button>}</div>}/>
      <div className="tab-list" role="tablist">{tabs.map(item => <button role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{item}{!['Overview'].includes(item) && <span className="tab-soon">SOON</span>}</button>)}</div>
      {tab === 'Overview' ? <div className="detail-grid"><Panel><PanelTitle>Device information</PanelTitle><div className="detail-list"><div><span>Hostname</span><strong>{device.hostname}</strong></div><div><span>Assigned name</span><strong>{device.assigned_name ?? 'Not assigned'}</strong></div><div><span>Device UUID</span><strong className="mono">{device.id}</strong></div><div><span>Enrollment</span><strong>{device.enrollment_state}</strong></div><div><span>Agent version</span><strong>{device.agent_version ?? 'Unavailable'}</strong></div><div><span>Enabled</span><strong>{device.enabled ? 'Yes' : 'No'}</strong></div></div></Panel><Panel><PanelTitle>Connection</PanelTitle><div className="connection-state"><span className="connection-icon"><Radio size={20}/></span><div><StatusBadge value={statuses.data?.agent_state ?? 'UNKNOWN'}/><p>{statuses.data?.network_state ? `Network reachability: ${statuses.data.network_state}` : 'Network status unavailable'}</p></div></div><div className="detail-list"><div><span>Last heartbeat</span><strong>{statuses.data?.last_heartbeat_at ? new Date(statuses.data.last_heartbeat_at).toLocaleString() : 'No heartbeat recorded'}</strong></div><div><span>Last seen</span><strong>{statuses.data?.last_seen_at ? new Date(statuses.data.last_seen_at).toLocaleString() : 'Never connected'}</strong></div><div><span>Status changed</span><strong>{statuses.data?.changed_at ? new Date(statuses.data.changed_at).toLocaleString() : '—'}</strong></div></div><div className="info-note"><ShieldCheck size={15}/> Status is based on authenticated server heartbeat receipt.</div></Panel></div> : <ComingSoon title={`${tab} data isn’t available yet`} description="The current server API does not provide this device data. This section will become active when the corresponding backend endpoint is implemented."/>}
    </> : !devices.isLoading && <Panel><div className="empty-inline">Device not found in the current server registry.</div></Panel>}
    {device && tab === 'Overview' && <SystemTelemetry id={id} />}
    {confirmDelete && device && <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !deleteDevice.isPending) setConfirmDelete(false) }}><section className="modal-card" role="alertdialog" aria-modal="true" aria-labelledby="delete-device-title" aria-describedby="delete-device-description"><span className="modal-icon red"><Trash2 size={18}/></span><h2 id="delete-device-title">Delete this device permanently?</h2><p id="delete-device-description">This permanently removes <strong>{device.assigned_name || device.hostname}</strong> and its device record ({device.id}). Its active connection will be closed and credentials revoked. To reconnect, it must be enrolled and approved again. This action cannot be undone.</p>{deleteDevice.isError && <div className="alert" role="alert">Device was not deleted. {deleteDevice.error.message}</div>}<div className="inline-actions"><Button disabled={deleteDevice.isPending} onClick={() => setConfirmDelete(false)}>Cancel</Button><Button className="danger" disabled={deleteDevice.isPending} onClick={() => deleteDevice.mutate()}>{deleteDevice.isPending ? 'Deleting…' : 'Permanently delete'}</Button></div></section></div>}
  </>
}
