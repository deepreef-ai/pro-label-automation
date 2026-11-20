import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Layers } from 'lucide-react'
import type { MaterialSummary } from '@contract/types'
import { Card, CardContent, CardHeader, EmptyState, QueryState, Skeleton, StatusChip } from '@/components/ui'
import type { UseApiResult } from '@/lib/api'
import { formatDate, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Paper needed for open jobs (planned metres incl. +10%) vs what is in stock. */
export function MaterialPanel({ query }: { query: UseApiResult<MaterialSummary> }) {
  const s = query.data
  return (
    <Card>
      <CardHeader
        title="Paper requirement"
        description={
          s
            ? `Open jobs · needed incl. +${formatPercent(s.planning_extra, { digits: 0 })} planning extra · as of ${formatDate(s.as_of)}`
            : 'Open jobs vs stock'
        }
        actions={
          s ? (
            s.shortages > 0 ? (
              <StatusChip tone="danger">{s.shortages} short</StatusChip>
            ) : (
              <StatusChip tone="ok">All covered</StatusChip>
            )
          ) : undefined
        }
      />
      <CardContent>
        <QueryState
          query={query}
          isEmpty={(d) => d.items.length === 0}
          loading={
            <div className="space-y-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="space-y-2">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-2 w-full" />
                </div>
              ))}
            </div>
          }
          empty={<EmptyState compact icon={Layers} title="No paper needed" description="No open jobs are waiting for paper." />}
        >
          {(d) => (
            <ul className="divide-y divide-border">
              {d.items.map((m) => {
                const short = m.status === 'short' || m.shortage_m > 0
                const cover = m.need_m > 0 ? Math.min(1, m.stock_m / m.need_m) : 1
                return (
                  <li key={m.item_id} className="space-y-2 py-4 first:pt-0 last:pb-0">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-medium text-foreground">{m.material}</p>
                        <p className="text-xs text-muted-foreground">
                          {m.item_id} · {m.width_mm} mm wide
                        </p>
                      </div>
                      {short ? (
                        <AlertTriangle className="size-4 shrink-0 text-danger" aria-label="Shortage" />
                      ) : (
                        <CheckCircle2 className="size-4 shrink-0 text-ok" aria-label="Covered" />
                      )}
                    </div>
                    <dl className="grid grid-cols-3 gap-2 text-sm">
                      <div>
                        <dt className="text-xs text-muted-foreground">Needed</dt>
                        <dd className="tabular font-medium text-foreground">{formatNumber(m.need_m)} m</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">In stock</dt>
                        <dd className="tabular font-medium text-foreground">{formatNumber(m.stock_m)} m</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-muted-foreground">Short</dt>
                        <dd className={cn('tabular font-medium', short ? 'text-danger-foreground' : 'text-muted-foreground')}>
                          {short ? `${formatNumber(m.shortage_m)} m` : '—'}
                        </dd>
                      </div>
                    </dl>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                      <div className={cn('h-full rounded-full', short ? 'bg-danger' : 'bg-ok')} style={{ width: `${cover * 100}%` }} />
                    </div>
                    {short && (
                      <p className="rounded-md bg-danger-soft px-2.5 py-1.5 text-xs text-danger-foreground">
                        Order {formatNumber(m.shortage_m)} m of {m.material} before these jobs reach the press.
                      </p>
                    )}
                    <div className="flex flex-wrap gap-1.5">
                      {m.jobs.map((j) => (
                        <Link
                          key={j.job_card}
                          to={`/jobs/${j.job_card}`}
                          title={`${j.client_name}: ${formatNumber(j.need_m)} m`}
                          className="rounded-sm border border-border bg-surface-muted px-1.5 py-0.5 text-2xs font-medium text-muted-foreground hover:border-border-strong hover:text-foreground"
                        >
                          {j.job_card} · {formatNumber(j.need_m)} m
                        </Link>
                      ))}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </QueryState>
      </CardContent>
    </Card>
  )
}
