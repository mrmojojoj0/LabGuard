import { api, json } from '../../lib/api'
import type { Room } from '../../lib/types'
export const roomsApi = {
  list: () => api<Room[]>('/rooms'),
  create: (input: Pick<Room, 'name' | 'description' | 'grid_rows' | 'grid_columns'>) => api<Room>('/rooms', json('POST', input)),
  update: (room: Room) => api<Room>(`/rooms/${room.id}`, json('PATCH', { name: room.name, description: room.description, grid_rows: room.grid_rows, grid_columns: room.grid_columns })),
}
