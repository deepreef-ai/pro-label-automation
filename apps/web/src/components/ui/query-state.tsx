import type { ReactNode } from 'react'
import { AlertTriangle, Database } from 'lucide-react'
import type { UseApiResult } from '@/lib/api'
import { Button } from './button'
import { EmptyState } from './empty-state'
import { PageSkeleton } from './skeleton'

/**
 * Renders loading / "No data yet" / error for a useApi() result, else children(data).
 *
 *   const q = useApi<Job[]>('/api/jobs')
 *   <QueryState query={q}>{(jobs) => <DataTable rows={jobs} … />}</QueryState>
 */
export function QueryState<T>({
  query,
  children,
  loading,
  empty,
  isEmpty,
}: {
  query: UseApiResult<T>
  children: (data: T) => ReactNode
  /** Custom loading UI. Default: PageSkeleton */
  loading?: ReactNode
  /** Custom empty UI */
  empty?: ReactNode
  /** Treat data as empty (e.g. empty array) */
  isEmpty?: (data: T) => boolean
}) {
  const { data, error, noData, refetch } = query
  if (data === undefined && query.loading) return <>{loading ?? <PageSkeleton />}</>
  if (noData || (data !== undefined && isEmpty?.(data))) {
    return (
      <>
        {empty ?? (
          <EmptyState icon={Database} title="No data yet" description="Nothing has been recorded here so far." />
        )}
      </>
    )
  }
  if (error) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Couldn't load this"
        description={error.message}
        action={
          <Button variant="secondary" size="sm" onClick={refetch}>
            Try again
          </Button>
        }
      />
    )
  }
  if (data === undefined) return <>{loading ?? <PageSkeleton />}</>
  return <>{children(data)}</>
}
