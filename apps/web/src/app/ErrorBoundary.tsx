import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link, isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { Button, EmptyState } from '@/components/ui'

function ErrorView({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        icon={AlertTriangle}
        title="Something went wrong on this screen"
        description={message ?? 'The rest of the app still works. Try again, or go back to the dashboard.'}
        action={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onRetry ?? (() => window.location.reload())}>
              <RotateCcw />
              Try again
            </Button>
            <Button asChild variant="ghost">
              <Link to="/">Go to Dashboard</Link>
            </Button>
          </div>
        }
      />
    </div>
  )
}

/** Catches render errors inside a page so the shell (sidebar, top bar) stays usable. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page crashed:', error, info.componentStack)
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      return <ErrorView message={this.state.error.message} onRetry={() => this.setState({ error: null })} />
    }
    return this.props.children
  }
}

/** Router-level error element (bad lazy chunk, loader error, etc.). */
export function RouteError() {
  const err = useRouteError()
  const message = isRouteErrorResponse(err)
    ? `${err.status} ${err.statusText}`
    : err instanceof Error
      ? err.message
      : undefined
  return (
    <div className="p-6">
      <ErrorView message={message} />
    </div>
  )
}
