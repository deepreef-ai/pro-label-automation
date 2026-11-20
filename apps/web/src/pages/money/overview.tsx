import { AlertTriangle, Banknote, Building2, Clock, Lock, Wallet } from 'lucide-react'
import type { CashPlan, Creditors, Debtors } from '@contract/types'
import { Card, CardContent, CardHeader, EmptyState, KpiCard, Skeleton, StatusChip } from '@/components/ui'
import { useApi } from '@/lib/api'
import { formatDateShort, formatINRShort } from '@/lib/format'
import { AgeingBar, daysBetween, LockChip } from './shared'
import { applyCreditors, applyDebtors, useMoneyOverlay } from './store'

export function OverviewTab({ go }: { go: (tab: string) => void }) {
  const overlay = useMoneyOverlay()
  const dq = useApi<Debtors>('/api/debtors')
  const cq = useApi<Creditors>('/api/creditors')
  const pq = useApi<CashPlan>('/api/cashplan')

  const debtors = dq.data ? applyDebtors(dq.data, overlay) : undefined
  const creditors = cq.data ? applyCreditors(cq.data, overlay) : undefined
  const cash = pq.data?.months[0]
  const lockedCount = debtors?.clients.filter((c) => c.lock_status === 'locked').length
  const atRisk =
    debtors?.clients
      .filter((c) => c.lock_status === 'at_risk' && c.locks_on && daysBetween(debtors.as_of, c.locks_on) <= 7)
      .sort((a, b) => (a.locks_on ?? '').localeCompare(b.locks_on ?? '')) ?? []
  const anyError = dq.error && !dq.noData

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          label="Receivable"
          icon={Wallet}
          value={debtors?.totals.outstanding ?? '—'}
          loading={dq.loading && !dq.data}
          footer={debtors ? `${debtors.clients.length} clients owe us` : undefined}
          onClick={() => go('debtors')}
        />
        <KpiCard
          label="Payable"
          icon={Building2}
          value={creditors?.totals.outstanding ?? '—'}
          loading={cq.loading && !cq.data}
          footer={creditors ? `${formatINRShort(creditors.totals.due_7d)} due in 7 days` : undefined}
          onClick={() => go('creditors')}
        />
        <KpiCard
          label="Overdue"
          icon={AlertTriangle}
          value={debtors?.totals.overdue ?? '—'}
          loading={dq.loading && !dq.data}
          footer={debtors ? `${formatINRShort(debtors.totals.at_risk)} at lock risk` : undefined}
          onClick={() => go('debtors')}
        />
        <KpiCard
          label="Locked clients"
          icon={Lock}
          value={lockedCount === undefined ? '—' : String(lockedCount)}
          loading={dq.loading && !dq.data}
          footer={debtors ? `${formatINRShort(debtors.totals.locked)} held up` : undefined}
          onClick={() => go('debtors')}
        />
        <KpiCard
          label="MSME due (7 days)"
          icon={Clock}
          value={creditors?.totals.msme_due_7d ?? '—'}
          loading={cq.loading && !cq.data}
          footer="45-day legal limit for MSME suppliers"
          onClick={() => go('creditors')}
        />
        <KpiCard
          label="Cash position"
          icon={Banknote}
          value={cash?.opening ?? '—'}
          loading={pq.loading && !pq.data}
          footer={
            cash && pq.data
              ? `Month-end ${formatINRShort(cash.closing)} · minimum ${formatINRShort(pq.data.min_cash)}`
              : undefined
          }
          onClick={() => go('cashplan')}
        />
      </div>

      {anyError ? (
        <Card>
          <EmptyState icon={AlertTriangle} title="Couldn't load debtors" description={dq.error?.message} compact />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3">
            <CardHeader title="Receivables ageing" description="Outstanding by days past due date" />
            <CardContent>
              {debtors ? (
                <AgeingBar buckets={debtors.totals.buckets} height="h-4" showLegend />
              ) : (
                <Skeleton className="h-16 w-full" />
              )}
            </CardContent>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader
              title="Locking this week"
              description={`Unpaid beyond due date + ${debtors?.grace_days ?? 15} days`}
              actions={atRisk.length > 0 ? <StatusChip tone="warn">{atRisk.length}</StatusChip> : undefined}
            />
            <CardContent className="pt-3">
              {!debtors ? (
                <Skeleton className="h-24 w-full" />
              ) : atRisk.length === 0 ? (
                <p className="text-sm text-muted-foreground">No client locks in the next 7 days.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {atRisk.slice(0, 5).map((c) => (
                    <li key={c.client_id} className="flex items-center justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate text-base font-medium text-foreground">{c.client_name}</div>
                        <div className="tabular text-xs text-muted-foreground">
                          {formatINRShort(c.outstanding)} · {c.max_days_past_due} days past due
                        </div>
                      </div>
                      <LockChip row={c} />
                    </li>
                  ))}
                </ul>
              )}
              {debtors && atRisk.length > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  First lock on {formatDateShort(atRisk[0].locks_on)}.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
