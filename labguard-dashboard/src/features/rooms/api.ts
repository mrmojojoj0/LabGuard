import { api, json } from '../../lib/api'
import type { Layout, Room } from '../../lib/types'
export const roomsApi = {
  list: () => api<Room[]>('/rooms'),
  create: (input: Pick<Room, 'name' | 'description' | 'grid_rows' | 'grid_columns'>) => api<Room>('/rooms', json('POST', input)),
  update: (room: Room) => api<Room>(`/rooms/${room.id}`, json('PATCH', { name: room.name, description: room.description })),
  layout: (id: string) => api<Layout>(`/rooms/${id}/layout`),
  saveLayout: (id: string, layout: Pick<Layout, 'room' | 'assignments'>) => api<Layout>(`/rooms/${id}/layout`, json('PUT', { rows: layout.room.grid_rows, columns: layout.room.grid_columns, assignments: layout.assignments })),
}
