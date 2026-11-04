import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
interface Props { children: ReactNode }
interface State { failed: boolean }
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }
  static getDerivedStateFromError(): State { return { failed: true } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('Dashboard rendering error', error, info.componentStack) }
  render() { if (this.state.failed) return <main className="fatal-error"><AlertTriangle size={24}/><h1>Something went wrong</h1><p>This page could not be displayed. Reload to try again.</p><button onClick={() => location.reload()}>Reload dashboard</button></main>; return this.props.children }
}
