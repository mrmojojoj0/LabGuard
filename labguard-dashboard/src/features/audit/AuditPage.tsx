import { useQuery } from '@tanstack/react-query'
import { FileClock } from 'lucide-react'
import { auditApi } from './api'
import { Empty, PageHeader, Panel, QueryError, Skeleton, StatusBadge } from '../../components/ui'
export function AuditPage() {
  const query = useQuery({ queryKey: ['audit'], queryFn: auditApi.list })
  return <><PageHeader eyebrow="SECURITY & GOVERNANCE" title="Audit logs" description="Recent administrator actions recorded by the LabGuard server." action={<span className="count-pill"><FileClock size={15}/>{query.data?.length ?? 0} events</span>}/>{query.isError && <QueryError error={query.error}/>}<Panel>{query.isLoading ? <Skeleton rows={7}/> : query.data?.length ? <div className="table-wrap"><table><thead><tr><th>Action</th><th>Actor</th><th>Target</th><th>Result</th><th>Time</th></tr></thead><tbody>{query.data.map(e => <tr key={e.id}><td><strong>{e.action.replaceAll('.', ' ')}</strong></td><td>{e.actor_type}{e.actor_id ? ` · ${e.actor_id.slice(0, 8)}` : ''}</td><td>{e.target_type}{e.target_id ? ` · ${e.target_id.slice(0, 12)}` : ''}</td><td><StatusBadge value={e.result}/></td><td>{new Date(e.occurred_at).toLocaleString()}</td></tr>)}</tbody></table></div> : <Empty title="No audit events" detail="The server has not returned any audit records yet."/>}</Panel></>
}
