import { api, json, setCsrfToken } from '../../lib/api'
import type { Admin, Role } from '../../lib/types'

export interface LoginResult { administrator: Admin; csrf_token: string; expires_at: string }
export const authApi = {
  login: async (username: string, password: string) => {
    const result = await api<LoginResult>('/auth/login', json('POST', { username, password }))
    setCsrfToken(result.csrf_token)
    return result.administrator
  },
  me: () => api<Admin>('/auth/me'),
  logout: async () => { await api<void>('/auth/logout', json('POST')); setCsrfToken(null) },
}
export const canManageLabs = (role?: Role) => role === 'LAB_ADMIN' || role === 'SUPER_ADMIN'
