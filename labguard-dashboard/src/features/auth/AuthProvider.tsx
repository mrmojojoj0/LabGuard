import { createContext, useContext, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { authApi } from './api'
import { ApiError, getCsrfToken, setCsrfToken } from '../../lib/api'
import type { Admin } from '../../lib/types'

interface AuthState { admin: Admin | null; ready: boolean; error: string | null; login: (u: string, p: string) => Promise<void>; logout: () => Promise<void> }
const AuthContext = createContext<AuthState | null>(null)
export const useAuth = () => { const value = useContext(AuthContext); if (!value) throw new Error('AuthProvider missing'); return value }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [admin, setAdmin] = useState<Admin | null>(null); const [ready, setReady] = useState(false); const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  useEffect(() => { let alive = true; authApi.me().then(a => { if (alive) setAdmin(a) }).catch(() => { if (alive) setAdmin(null) }).finally(() => { if (alive) setReady(true) }); return () => { alive = false } }, [])
  const login = async (username: string, password: string) => { setError(null); try { setAdmin(await authApi.login(username, password)); navigate('/') } catch (e) { setError(e instanceof Error ? e.message : 'Login failed'); throw e } }
  const logout = async () => { try { if (!getCsrfToken()) throw new ApiError('Session security token is unavailable. Sign in again to log out.', 403); await authApi.logout() } finally { setCsrfToken(null); setAdmin(null); navigate('/login') } }
  const value = useMemo(() => ({ admin, ready, error, login, logout }), [admin, ready, error])
  if (!ready) return <div className="boot-screen"><span className="brand-mark">L</span><p>Connecting to LabGuard…</p></div>
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function LoginPage() {
  const { login, error } = useAuth(); const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [busy, setBusy] = useState(false); const location = useLocation()
  const submit = async (event: FormEvent) => { event.preventDefault(); setBusy(true); try { await login(username, password) } catch { /* rendered below */ } finally { setBusy(false) } }
  return <main className="login-shell"><section className="login-card"><div className="brand"><span className="brand-mark">L</span><div><strong>LabGuard</strong><small>ADMIN CONSOLE</small></div></div><p className="eyebrow">SECURE ADMINISTRATOR ACCESS</p><h1>Welcome back</h1><p className="muted">Sign in with your LabGuard administrator account.</p><form onSubmit={submit} className="form-stack"><label>Username<input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required /></label><label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></label>{error && <div className="alert" role="alert">{error}</div>}<button className="button primary full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'} <span>→</span></button></form><p className="login-foot">Protected session · {location.pathname === '/login' ? 'LabGuard server authentication' : 'Please authenticate'}</p></section><div className="login-side"><div className="login-orbit orbit-one"/><div className="login-orbit orbit-two"/><span className="eyebrow">INSTITUTIONAL DEVICE MANAGEMENT</span><h2>A clear view of every lab.</h2><p>Monitor fleet health, manage room layouts, and review enrollment activity from one secure workspace.</p><div className="login-stat"><span className="live-dot"/> Connected to your LabGuard server</div></div></main>
}
