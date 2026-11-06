import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from 'react'
import { DragDropProvider, useDraggable, useDroppable } from '@dnd-kit/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, Check, ChevronDown, Computer, GripVertical, LayoutGrid, Monitor, Pencil, Plus, Presentation, Save, X } from 'lucide-react'
import { roomsApi } from './api'
import { devicesApi } from '../devices/api'
import { Button, Empty, PageHeader, Panel, PanelTitle, QueryError, Skeleton } from '../../components/ui'
import { canManageLabs } from '../auth/api'
import { useAuth } from '../auth/AuthProvider'
import type { Device, DeviceStatus, Layout, Room } from '../../lib/types'
import { useToast } from '../../components/Toast'

const EMPTY_ASSIGNMENTS: Layout['assignments'] = []

type DeviceWithStatus = { device: Device; status: DeviceStatus | null }
type DeviceCardProps = DeviceWithStatus & {
  editable: boolean

  onInspect: (device: Device) => void
}

function LabStatus({ value }: { value: string }) {
  const label = value.replaceAll('_', ' ').toLowerCase()
  return <span className={`lab-status lab-status-${value.toLowerCase().replaceAll('_', '-')}`}><i />{label}</span>
}

function DeviceCard({ device, status, editable, onInspect }: DeviceCardProps) {
  const canDrag = editable && device.enabled && device.enrollment_state === 'APPROVED'
  const drag = useDraggable({ id: `device:${device.id}`, disabled: !canDrag })
  const state = device.enrollment_state === 'PENDING' ? 'PENDING' : status?.agent_state ?? 'NEVER_CONNECTED'
  const displayName = device.assigned_name || device.hostname
  return <article ref={drag.ref} className={`lab-device-card ${drag.isDragging ? 'is-dragging' : ''} ${canDrag ? '' : 'is-static'}`}>
    <button type="button" className="lab-device-main" onClick={() => onInspect(device)} aria-label={`View ${displayName} details`}>
      <div  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        
      <span className="lab-device-icon"><Monitor size={19} /></span>
      <span className="lab-device-label"><strong title={displayName}>{displayName}</strong><small>{device.hostname}</small></span>
      </div>
      <LabStatus value={state} />
    </button>

    {canDrag && <button ref={drag.handleRef} type="button" className="lab-drag-handle" aria-label={`Drag ${displayName}`} title="Drag to move"><GripVertical size={17} /></button>}
  </article>
}

function FloorCell({ row, column, device, status, editable, onInspect }: {
  row: number; column: number; device?: Device; status: DeviceStatus | null; editable: boolean; onInspect: (device: Device) => void
}) {
  const droppable = useDroppable({ id: `cell:${row}:${column}`, disabled: !editable })
  return <div ref={droppable.ref} className={`lab-floor-cell ${droppable.isDropTarget ? 'is-drop-target' : ''} ${device ? 'has-device' : 'is-empty'}`}>
    <span className="lab-cell-coordinate">R{row + 1} · C{column + 1}</span>
    {device
      ? <DeviceCard device={device} status={status} editable={editable} onInspect={onInspect} />
      : <div className="lab-empty-cell"><Plus size={17} /><span>{editable ? 'Drop computer here' : 'Empty workstation'}</span></div>}
  </div>
}

function UnassignedRail({ devices, editable, onInspect }: {
  devices: DeviceWithStatus[]; editable: boolean; onInspect: (device: Device) => void
}) {
  const drop = useDroppable({ id: 'unassigned', disabled: !editable })
  return <aside ref={drop.ref} className={`lab-unassigned-rail ${drop.isDropTarget ? 'is-drop-target' : ''}`}>
    <div className="lab-rail-heading"><div><h3>Unassigned</h3><p>Drag a computer into an open workstation.</p></div><span className="lab-count-pill">{devices.length}</span></div>
    <div className="lab-unassigned-list">
      {devices.length ? devices.map(({ device, status }) => <DeviceCard key={device.id} device={device} status={status} editable={editable} onInspect={onInspect} />)
        : <div className="lab-rail-empty"><Check size={19} /><strong>All approved devices are placed</strong><span>Drag a device here to remove it from the floor plan.</span></div>}
    </div>
    {editable && <div className="lab-remove-hint"><ArrowDown size={14} />Drop an assigned computer here to unassign it</div>}
  </aside>
}

function DeviceInspector({ item, status, coordinate, onClose }: {
  item: Device; status: DeviceStatus | null; coordinate?: string; onClose: () => void
}) {
  const state = item.enrollment_state === 'PENDING' ? 'PENDING' : status?.agent_state ?? 'NEVER_CONNECTED'
  return <div className="lab-inspector-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <aside className="lab-device-inspector" role="dialog" aria-modal="true" aria-label={`${item.assigned_name || item.hostname} details`}>
      <div className="lab-inspector-top"><span className="lab-inspector-icon"><Computer size={21} /></span><button className="icon-button" onClick={onClose} aria-label="Close device details"><X size={18} /></button></div>
      <p className="eyebrow">DEVICE DETAILS</p><h2>{item.assigned_name || item.hostname}</h2><p className="lab-inspector-hostname">{item.hostname}</p>
      <LabStatus value={state} />
      <dl className="lab-inspector-list">
        <div><dt>Assigned name</dt><dd>{item.assigned_name || 'Not assigned'}</dd></div>
        <div><dt>Device ID</dt><dd className="lab-mono">{item.id}</dd></div>
        <div><dt>Enrollment</dt><dd>{item.enrollment_state}</dd></div>
        <div><dt>Agent version</dt><dd>{item.agent_version || 'Unavailable'}</dd></div>
        <div><dt>Connection</dt><dd>{status ? (status.connected ? 'Connected' : 'Disconnected') : 'Not connected'}</dd></div>
        <div><dt>Network</dt><dd>{status?.network_state || 'Unknown'}</dd></div>
        <div><dt>Last heartbeat</dt><dd>{status?.last_heartbeat_at ? new Date(status.last_heartbeat_at).toLocaleString() : 'None recorded'}</dd></div>
        <div><dt>Workstation</dt><dd>{coordinate || 'Unassigned'}</dd></div>
      </dl>
      <p className="lab-inspector-note">Status is based on authenticated heartbeats received by the server.</p>
      <a href={`/devices/${item.id}`} target="_blank" rel="noopener noreferrer" className="lab-inspector-link ">View full device details</a>
    </aside>
  </div>
}

function assignmentsEqual(a: Layout['assignments'], b: Layout['assignments']) {
  const normalize = (items: Layout['assignments']) => [...items].sort((x, y) => x.device_id.localeCompare(y.device_id))
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b))
}

function isValidLayout(layout: Layout) {
  const { grid_rows: rows, grid_columns: columns } = layout.room
  if (!Number.isInteger(rows) || !Number.isInteger(columns) || rows < 1 || rows > 100 || columns < 1 || columns > 100) return false
  if (layout.assignments.length > 1000) return false
  const devices = new Set<string>()
  const cells = new Set<string>()
  for (const assignment of layout.assignments) {
    const cell = `${assignment.row}:${assignment.column}`
    if (!Number.isInteger(assignment.row) || !Number.isInteger(assignment.column) || assignment.row < 0 || assignment.column < 0 || assignment.row >= rows || assignment.column >= columns) return false
    if (devices.has(assignment.device_id) || cells.has(cell)) return false
    devices.add(assignment.device_id); cells.add(cell)
  }
  return true
}

export function RoomsPage() {
  const { admin } = useAuth()
  const toast = useToast()
  const editable = canManageLabs(admin?.role)
  const qc = useQueryClient()
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: roomsApi.list })
  const devices = useQuery({ queryKey: ['devices'], queryFn: devicesApi.list })
  const statusIds = devices.data?.map(device => device.id) ?? []
  const statuses = useQuery({ queryKey: ['statuses', statusIds], queryFn: () => devicesApi.statuses(devices.data ?? []), enabled: !!devices.data?.length, refetchInterval: false })
  const [selectedRoomId, setSelectedRoomId] = useState('')
  const [loadedRoomId, setLoadedRoomId] = useState('')
  const [draft, setDraft] = useState<Layout | null>(null)
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null)
  const [editingRoom, setEditingRoom] = useState<Room | null>(null)
  const [creatingRoom, setCreatingRoom] = useState(false)
  const [notice, setNotice] = useState('')
  const layout = useQuery({ queryKey: ['room-layout', selectedRoomId], queryFn: () => roomsApi.layout(selectedRoomId), enabled: !!selectedRoomId })
  const selectedRoom = rooms.data?.find(room => room.id === selectedRoomId) ?? null
  const statusById = useMemo(() => new Map((statuses.data ?? []).filter((item): item is DeviceStatus => item !== null).map(item => [item.device_id, item])), [statuses.data])

  useEffect(() => {
    const onDeviceDeleted = (event: Event) => {
      const id = (event as CustomEvent<{ deviceId: string }>).detail?.deviceId
      if (!id) return
      setSelectedDevice(current => current?.id === id ? null : current)
      setDraft(current => current ? { ...current, assignments: current.assignments.filter(item => item.device_id !== id) } : current)
      void qc.invalidateQueries({ queryKey: ['room-layout'] })
    }
    window.addEventListener('labguard:device-deleted', onDeviceDeleted)
    return () => window.removeEventListener('labguard:device-deleted', onDeviceDeleted)
  }, [qc])

  useEffect(() => {
    if (!selectedRoomId && rooms.data?.length) setSelectedRoomId(rooms.data[0].id)
  }, [rooms.data, selectedRoomId])
  useEffect(() => {
    if (layout.data && layout.data.room.id === selectedRoomId && loadedRoomId !== selectedRoomId) {
      setDraft(structuredClone(layout.data))
      setLoadedRoomId(selectedRoomId)
    }
  }, [layout.data, selectedRoomId, loadedRoomId])

  const saveRoom = useMutation({
    mutationFn: (room: Room) => room.id
      ? roomsApi.update(room)
      : roomsApi.create({ name: room.name, description: room.description, grid_rows: room.grid_rows, grid_columns: room.grid_columns }),
    onSuccess: async saved => {
      await qc.invalidateQueries({ queryKey: ['rooms'] })
      setEditingRoom(null); setCreatingRoom(false)
      if (creatingRoom || !selectedRoomId) { setSelectedRoomId(saved.id); setLoadedRoomId(''); setDraft(null) }
      toast('Room saved.')
    },
    onError: (error: Error) => toast(error.message, 'error'),
  })
  const saveLayout = useMutation({
    mutationFn: (value: Layout) => roomsApi.saveLayout(value.room.id, value),
    onSuccess: result => {
      setDraft(structuredClone(result))
      setLoadedRoomId(result.room.id)
      qc.setQueryData(['room-layout', result.room.id], result)
      void qc.invalidateQueries({ queryKey: ['rooms'] })
      setNotice('Floor plan saved.')
      toast('Floor plan saved.')
    },
    onError: (error: Error) => {
      setNotice(error.message)
      toast(`Layout was not saved. Your changes are still here. ${error.message}`, 'error')
    },
  })

  const savedLayout = layout.data
  const layoutIsValid = !!draft && isValidLayout(draft)
  const isDirty = !!draft && !!savedLayout && (
    draft.room.grid_rows !== savedLayout.room.grid_rows || draft.room.grid_columns !== savedLayout.room.grid_columns ||
    !assignmentsEqual(draft.assignments, savedLayout.assignments)
  )
  const assignedIds = new Set(draft?.assignments.map(item => item.device_id) ?? EMPTY_ASSIGNMENTS.map(item => item.device_id))
  const eligibleDevices = (devices.data ?? []).filter(device => device.enabled && device.enrollment_state === 'APPROVED')
  const unassigned = eligibleDevices.filter(device => !assignedIds.has(device.id)).map(device => ({ device, status: statusById.get(device.id) ?? null }))
  const pending = (devices.data ?? []).filter(device => device.enrollment_state === 'PENDING')
  const assignedDevices = (draft?.assignments ?? EMPTY_ASSIGNMENTS).map(assignment => ({
    assignment,
    device: devices.data?.find(device => device.id === assignment.device_id),
  })).filter((item): item is { assignment: Layout['assignments'][number]; device: Device } => !!item.device)
  const stats = {
    assigned: draft?.assignments.length ?? 0,
    online: assignedDevices.filter(item => statusById.get(item.device.id)?.agent_state === 'ONLINE').length,
    delayed: assignedDevices.filter(item => statusById.get(item.device.id)?.agent_state === 'DELAYED').length,
    offline: assignedDevices.filter(item => ['OFFLINE', 'NEVER_CONNECTED'].includes(statusById.get(item.device.id)?.agent_state ?? 'NEVER_CONNECTED')).length,
  }
  const inspectorStatus = selectedDevice ? statusById.get(selectedDevice.id) ?? null : null
  const inspectorAssignment = selectedDevice ? draft?.assignments.find(item => item.device_id === selectedDevice.id) : undefined
  const gridStyle: CSSProperties | undefined = draft ? {
    gridTemplateColumns: `repeat(${draft.room.grid_columns}, minmax(164px, 1fr))`,
    minWidth: `max(100%, ${draft.room.grid_columns * 164}px)`,
  } : undefined

  const setRoom = (roomId: string) => {
    if (roomId === selectedRoomId) return
    if (isDirty && !window.confirm('Discard unsaved floor plan changes and switch rooms?')) return
    setSelectedRoomId(roomId); setLoadedRoomId(''); setDraft(null); setSelectedDevice(null); setNotice('')
  }
  const handleDrop = (event: Parameters<NonNullable<React.ComponentProps<typeof DragDropProvider>['onDragEnd']>>[0]) => {
    if (!draft || !editable || event.canceled || !event.operation.target) return
    const sourceId = event.operation.source?.id
    if (sourceId === undefined || sourceId === null) return
    const source = String(sourceId)
    if (!source.startsWith('device:')) return
    const deviceId = source.slice('device:'.length)
    const targetId = String(event.operation.target.id)
    if (targetId === 'unassigned') {
      setDraft({ ...draft, assignments: draft.assignments.filter(item => item.device_id !== deviceId) })
      return
    }
    const match = /^cell:(\d+):(\d+)$/.exec(targetId)
    if (!match) return
    const row = Number(match[1]); const column = Number(match[2])
    if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0 || row >= draft.room.grid_rows || column >= draft.room.grid_columns) return
    const sourceAssignment = draft.assignments.find(item => item.device_id === deviceId)
    const targetAssignment = draft.assignments.find(item => item.row === row && item.column === column)
    if (sourceAssignment && sourceAssignment.row === row && sourceAssignment.column === column) return
    let assignments = draft.assignments.filter(item => item.device_id !== deviceId)
    if (sourceAssignment && targetAssignment) {
      assignments = assignments.map(item => item.device_id === targetAssignment.device_id
        ? { ...item, row: sourceAssignment.row, column: sourceAssignment.column }
        : item)
    } else if (targetAssignment) {
      assignments = assignments.filter(item => item.device_id !== targetAssignment.device_id)
    }
    assignments.push({ device_id: deviceId, row, column })
    setDraft({ ...draft, assignments: assignments.sort((a, b) => a.row - b.row || a.column - b.column) })
  }

  const blankRoom = (): Room => ({ id: '', name: '', description: '', grid_rows: 5, grid_columns: 8 })
  const closeRoomForm = () => { setEditingRoom(null); setCreatingRoom(false) }

  return <>
    <PageHeader eyebrow="LAB ORGANIZATION" title="Rooms & labs" description="Arrange lab computers on an interactive floor plan."
      action={<div className="lab-page-actions">{rooms.data?.length ? <label className="lab-room-select"><span>Room</span><select value={selectedRoomId} onChange={event => setRoom(event.target.value)} aria-label="Select room">{rooms.data.map(room => <option key={room.id} value={room.id}>{room.name}</option>)}</select><ChevronDown size={15} /></label> : null}
        {editable && <Button className="primary" onClick={() => { setEditingRoom(blankRoom()); setCreatingRoom(true) }}><Plus size={16} /> Add room</Button>}</div>} />

    {rooms.isError && <QueryError error={rooms.error} />}
    {notice && <div className="lab-layout-notice" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss notice"><X size={14} /></button></div>}

    {(editingRoom || creatingRoom) && <Panel className="lab-room-form-panel"><PanelTitle>{creatingRoom ? 'Create room' : 'Edit room details'}</PanelTitle>
      <form className="lab-room-form" onSubmit={(event: FormEvent) => { event.preventDefault(); if (editingRoom) saveRoom.mutate(editingRoom) }}>
        <label>Room name<input required maxLength={100} value={editingRoom?.name ?? ''} onChange={event => editingRoom && setEditingRoom({ ...editingRoom, name: event.target.value })} /></label>
        <label>Description<input maxLength={500} value={editingRoom?.description ?? ''} onChange={event => editingRoom && setEditingRoom({ ...editingRoom, description: event.target.value })} /></label>
        {creatingRoom && <><label>Rows<input type="number" min={1} max={100} value={editingRoom?.grid_rows ?? 5} onChange={event => editingRoom && setEditingRoom({ ...editingRoom, grid_rows: Number(event.target.value) })} /></label>
          <label>Columns<input type="number" min={1} max={100} value={editingRoom?.grid_columns ?? 8} onChange={event => editingRoom && setEditingRoom({ ...editingRoom, grid_columns: Number(event.target.value) })} /></label></>}
        <div className="lab-room-form-actions"><Button type="button" onClick={closeRoomForm}>Cancel</Button><Button className="primary" type="submit" disabled={saveRoom.isPending || !editingRoom?.name.trim()}><Save size={15} />{saveRoom.isPending ? 'Saving…' : creatingRoom ? 'Create room' : 'Save details'}</Button></div>
      </form>
    </Panel>}

    {rooms.isLoading ? <Panel><Skeleton rows={4} /></Panel> : !rooms.data?.length ? <Panel><Empty title="No rooms configured" detail="Create a room to start building your laboratory floor plan." /></Panel> : selectedRoom && <>
      {editingRoom === null && <div className="lab-room-heading"><div><span className="lab-room-kicker">FLOOR PLAN</span><h2>{selectedRoom.name}</h2><p>{selectedRoom.description || 'Computer workstations and room status'}</p></div>
        {editable && <Button onClick={() => { setEditingRoom({ ...selectedRoom }); setCreatingRoom(false) }}><Pencil size={15} /> Edit room</Button>}</div>}
      {layout.isLoading && <Panel className="lab-layout-loading"><Skeleton rows={7} /></Panel>}
      {layout.isError && <Panel><QueryError error={layout.error} /><Button onClick={() => void layout.refetch()}>Retry floor plan</Button></Panel>}
      {draft && savedLayout && <DragDropProvider onDragEnd={handleDrop}>
        <div className="lab-floor-workspace">
          <div className="lab-floor-main">
            <Panel className="lab-floor-panel">
              <div className="lab-floor-toolbar"><div className="lab-floor-title"><span className="lab-floor-icon"><LayoutGrid size={18} /></span><div><strong>{selectedRoom.name} floor plan</strong><span>{draft.room.grid_rows} rows × {draft.room.grid_columns} columns</span></div></div>
                {editable && <div className="lab-dimensions"><label>Rows<input aria-label="Grid rows" type="number" min={1} max={100} value={draft.room.grid_rows} onChange={event => setDraft({ ...draft, room: { ...draft.room, grid_rows: Number(event.target.value) } })} /></label><label>Columns<input aria-label="Grid columns" type="number" min={1} max={100} value={draft.room.grid_columns} onChange={event => setDraft({ ...draft, room: { ...draft.room, grid_columns: Number(event.target.value) } })} /></label></div>}
              </div>
              <div className="lab-stats-row"><div><span>Assigned</span><strong>{stats.assigned}</strong></div><div className="is-online"><span>Online</span><strong>{stats.online}</strong></div><div className="is-delayed"><span>Delayed</span><strong>{stats.delayed}</strong></div><div className="is-offline"><span>Offline</span><strong>{stats.offline}</strong></div><div className="is-unassigned"><span>Unassigned</span><strong>{unassigned.length}</strong></div></div>
              <div className="lab-floor-scroll" aria-label="Scrollable laboratory floor plan">
                <div className="lab-floor-grid" style={gridStyle}>
                  <div className="lab-front-indicator"><span className="lab-front-arrow"><ArrowDown size={16} /></span><span>FRONT OF ROOM</span><div className="lab-instructor-desk"><Presentation size={17} /><strong>Instructor desk</strong></div></div>
                  {Array.from({ length: draft.room.grid_rows * draft.room.grid_columns }, (_, index) => {
                    const row = Math.floor(index / draft.room.grid_columns)
                    const column = index % draft.room.grid_columns
                    const assignment = draft.assignments.find(item => item.row === row && item.column === column)
                    const device = assignment ? devices.data?.find(item => item.id === assignment.device_id) : undefined
                    return <FloorCell key={`${row}:${column}`} row={row} column={column} device={device} status={device ? statusById.get(device.id) ?? null : null} editable={editable} onInspect={setSelectedDevice} />
                  })}
                </div>
              </div>
              <div className="lab-floor-legend"><span><i className="legend-dot online" />Online</span><span><i className="legend-dot delayed" />Delayed</span><span><i className="legend-dot offline" />Offline</span><span><i className="legend-dot quarantined" />Quarantined</span><span><i className="legend-dot pending" />Pending</span></div>
            </Panel>
            {editable && isDirty && <div className="lab-save-bar"><span><strong>Unsaved floor plan changes</strong><small>Changes stay local until you save.</small></span><div><Button disabled={saveLayout.isPending} onClick={() => { setDraft(structuredClone(savedLayout)); setNotice('Unsaved changes discarded.') }}>Discard</Button><Button className="primary" disabled={saveLayout.isPending || !layoutIsValid} onClick={() => saveLayout.mutate(draft)}><Save size={15} />{saveLayout.isPending ? 'Saving…' : 'Save floor plan'}</Button></div></div>}
            {editable && draft && !layoutIsValid && <div className="lab-validation-error" role="alert">Grid dimensions must be whole numbers from 1 to 100. Each device and cell can only be assigned once, and placements must fit inside the grid.</div>}
            {saveLayout.isError && <div className="lab-save-error" role="alert">{saveLayout.error.message} Your edits are preserved. Adjust the layout and try again.</div>}
          </div>
          <UnassignedRail devices={unassigned} editable={editable} onInspect={setSelectedDevice} />
        </div>
        {pending.length > 0 && <div className="lab-pending-note"><LabStatus value="PENDING" /><span>{pending.length} device{pending.length === 1 ? '' : 's'} awaiting enrollment approval cannot be placed yet.</span></div>}
        {selectedDevice && <DeviceInspector item={selectedDevice} status={inspectorStatus} coordinate={inspectorAssignment ? `Row ${inspectorAssignment.row + 1}, column ${inspectorAssignment.column + 1}` : undefined} onClose={() => setSelectedDevice(null)} />}
      </DragDropProvider>}
    </>}
  </>
}
