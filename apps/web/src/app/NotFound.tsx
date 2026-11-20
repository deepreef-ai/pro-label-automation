import { Link, useLocation } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { Button, EmptyState } from '@/components/ui'

export default function NotFound() {
  const { pathname } = useLocation()
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        icon={Compass}
        titleAs="h1"
        title="Page not found"
        description={
          <>
            There is no screen at <code className="rounded-sm bg-surface-muted px-1 py-0.5 text-foreground">{pathname}</code>.
            Use the menu or press Ctrl K to search.
          </>
        }
        action={
          <Button asChild>
            <Link to="/">Back to Dashboard</Link>
          </Button>
        }
      />
    </div>
  )
}
