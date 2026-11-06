import { useQuery } from '@tanstack/react-query'
import { Cpu, MemoryStick, HardDrive, Activity } from 'lucide-react'
import { devicesApi } from './api'
import { Panel, PanelTitle, QueryError, Skeleton } from '../../components/ui'
import type { TelemetrySample } from '../../lib/types'
import './telemetry.css'

function formatBytes(value: number) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']; let amount = value; let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++ }
  return `${amount.toFixed(unit ? 1 : 0)} ${units[unit]}`
}

function formatUptime(value: number) {
  if (!Number.isFinite(value) || value < 0) return 'Unavailable'
  const days = Math.floor(value / 86400); const hours = Math.floor(value % 86400 / 3600); const minutes = Math.floor(value % 3600 / 60)
  return `${days}d ${hours}h ${minutes}m`
}

function MetricChart({ title, values, color }: { title: string; values: number[]; color: string }) {
  if (values.length < 2) return <div className="telemetry-chart"><div><strong>{title}</strong><span>History appears after two reports</span></div><div className="telemetry-chart-empty">Collecting history</div></div>
  const width = 320; const height = 92; const pad = 8
  const points = values.map((value, index) => {
    const x = pad + index * (width - pad * 2) / (values.length - 1)
    const y = height - pad - Math.min(100, Math.max(0, value)) * (height - pad * 2) / 100
    return `${x},${y}`
  }).join(' ')
  return <div className="telemetry-chart"><div><strong>{title}</strong><span>{values.at(-1)?.toFixed(1)}%</span></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} historical utilization`}><line x1={pad} x2={width - pad} y1={height / 2} y2={height / 2} /><polyline points={points} style={{ stroke: color }} /></svg><small>Recent reports · last {values.length}</small></div>
}

export function SystemTelemetry({ id }: { id: string }) {
  const latest = useQuery({ queryKey: ['telemetry', id], queryFn: () => devicesApi.telemetry(id), refetchInterval: 30_000 })
  const history = useQuery({ queryKey: ['telemetry-history', id], queryFn: () => devicesApi.telemetryHistory(id), refetchInterval: 30_000 })
  const data = latest.data?.snapshot
  const samples: TelemetrySample[] = history.data?.samples ?? []
  const totalBytes = data?.storage_partitions.reduce((sum, item) => sum + item.total_bytes, 0) ?? 0
  const usedBytes = data?.storage_partitions.reduce((sum, item) => sum + item.used_bytes, 0) ?? 0
  const diskPercent = totalBytes ? usedBytes / totalBytes * 100 : null
  if (latest.isError) return <Panel><PanelTitle>System telemetry</PanelTitle><QueryError error={latest.error} /></Panel>
  if (latest.isLoading) return <Panel><PanelTitle>System telemetry</PanelTitle><Skeleton rows={4} /></Panel>
  if (!data) return <Panel><PanelTitle>System telemetry</PanelTitle><div className="telemetry-unavailable"><Activity size={18} /><strong>Waiting for the first telemetry report</strong><span>Metrics appear after the agent connects and completes its initial collection.</span></div></Panel>
  const os = data.operating_system
  return <div className="telemetry-stack">
    <Panel className='telemetry-panel'><PanelTitle aside={<span className={`telemetry-freshness ${latest.data?.stale ? 'is-stale' : ''}`}>{latest.data?.stale ? 'STALE' : 'CURRENT'}</span>}>System overview</PanelTitle>
      <div className="telemetry-last-update">Last update received {new Date(data.received_at).toLocaleString()}{latest.data?.stale ? ` · older than ${latest.data.stale_after_seconds}s` : ''}</div>
      <div className="telemetry-metrics">
        <div><Cpu size={16} /><span>CPU utilization</span><strong>{data.cpu.utilization_percent.toFixed(1)}%</strong><small>{data.cpu.processor_name || 'Processor name unavailable'} · {data.cpu.logical_processors} logical{data.cpu.physical_cores ? ` · ${data.cpu.physical_cores} cores` : ''}</small></div>
        <div><MemoryStick size={16} /><span>Memory utilization</span><strong>{data.memory.utilization_percent.toFixed(1)}%</strong><small>{formatBytes(data.memory.used_bytes)} used of {formatBytes(data.memory.total_bytes)}</small></div>
        <div><HardDrive size={16} /><span>Disk utilization</span><strong>{diskPercent === null ? 'Unavailable' : `${diskPercent.toFixed(1)}%`}</strong><small>{data.storage_partitions.length} mounted volume{data.storage_partitions.length === 1 ? '' : 's'}</small></div>
      </div>
      {history.isError && <QueryError error={history.error} />}
      <div className="telemetry-charts"><MetricChart title="CPU" color="#4a83d4" values={samples.map(item => item.cpu_percent)} /><MetricChart title="Memory" color="#20a078" values={samples.map(item => item.memory_percent)} /><MetricChart title="Disk" color="#c28b26" values={samples.flatMap(item => item.disk_percent === null ? [] : [item.disk_percent])} /></div>
    </Panel>
    <div className="detail-grid">
      <Panel><PanelTitle>Operating system & uptime</PanelTitle><div className="detail-list">
        <div><span>Windows edition</span><strong>{os.edition || 'Unavailable'}</strong></div><div><span>Version</span><strong>{os.version || 'Unavailable'}</strong></div><div><span>Build</span><strong>{os.build_number || 'Unavailable'}</strong></div><div><span>Architecture</span><strong>{os.architecture || 'Unavailable'}</strong></div><div><span>Hostname</span><strong>{os.hostname || 'Unavailable'}</strong></div><div><span>Uptime</span><strong>{formatUptime(data.uptime_seconds)}</strong></div><div><span>Boot time</span><strong>{new Date(data.boot_time).toLocaleString()}</strong></div>
      </div></Panel>
      <Panel><PanelTitle>Storage volumes</PanelTitle>{data.storage_partitions.length ? <div className="telemetry-list">{data.storage_partitions.map((part, index) => <div className="telemetry-volume" key={`${part.mountpoint}-${index}`}><div><strong>{part.mountpoint || part.device || 'Volume'}</strong><span>{part.filesystem || 'Filesystem unavailable'}</span></div><strong>{part.utilization_percent.toFixed(1)}%</strong><div className="telemetry-progress"><i style={{ width: `${Math.min(100, part.utilization_percent)}%` }} /></div><small>{formatBytes(part.used_bytes)} used · {formatBytes(part.free_bytes)} free of {formatBytes(part.total_bytes)}</small></div>)}</div> : <div className="telemetry-muted">Storage details unavailable.</div>}</Panel>
    </div>
    <Panel><PanelTitle>Network interfaces</PanelTitle>{data.network_interfaces.length ? <div className="telemetry-interface-grid">{data.network_interfaces.map((item, index) => <div className="telemetry-interface" key={`${item.name}-${index}`}><div><strong>{item.name}</strong><span className={`telemetry-interface-state ${item.status.toLowerCase()}`}>{item.status}</span></div><small>MAC {item.mac_address || 'Unavailable'}{item.speed_mbps ? ` · ${item.speed_mbps.toLocaleString()} Mbps` : ''}</small><small>IPv4 {item.ipv4_addresses.join(', ') || 'Unavailable'}</small><small>IPv6 {item.ipv6_addresses.join(', ') || 'Unavailable'}</small></div>)}</div> : <div className="telemetry-muted">Network interface details unavailable.</div>}</Panel>
  </div>
}
