import { useMemo, useState } from 'react'
import { AlertTriangle, CalendarClock, Unlock } from 'lucide-react'
import type { DebtorRow, Debtors, ReleaseLockResult } from '@contract/types'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  QueryState,
  Segmented,
  StatusChip,
  Textarea,
  Tooltip,
  toast,
  type Column,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { useRole } from '@/lib/role'
import { formatDate, formatDateShort, formatINR, formatINRShort } from '@/lib/format'
import { AgeingBar, daysBetween, LockChip, Stat } from './shared'
import { applyDebtors, isMock, moneyStore, useMoneyOverlay } from './store'

type Filter = 'all' | 'at_risk' | 'locked'

export function DebtorsTab({ initialFilter }: { initialFilter?: string | null }) {
  const overlay = useMoneyOverlay()
  const role = useRole()
  const isOwner = role === 'owner'
  const q = useApi<Debtors>('/api/debtors')
  const [filter, setFilter] = useState<Filter>(
    initialFilter === 'at_risk' || initialFilter === 'locked' ? initialFilter : 'all',
  )
  const [releasing, setReleasing] = useState<DebtorRow | null>(null)
  const [released, setReleased] = useState<Record<string, ReleaseLockResult>>({})

  const columns: Column<DebtorRow>[] = useMemo(
    () => [
      {
        key: 'client_name',
        header: 'Client',
        cell: (r) => (
          <div className="min-w-0">
            <div className="font-medium">{r.client_name}</div>
            <div className="text-xs text-muted-foreground">{r.credit_days}-day credit</div>
          </div>
        ),
      },
      {
        key: 'outstanding',
        header: 'Outstanding',
        align: 'right',
        cell: (r) => formatINR(r.outstanding),
      },
      {
        key: 'ageing',
        header: 'Ageing',
        sortable: false,
        width: 'w-40',
        cell: (r) => <AgeingBar buckets={r.buckets} height="h-2" className="min-w-28" />,
      },
      {
        key: 'max_days_past_due',
        header: 'Days late',
        align: 'right',
        cell: (r) => (r.max_days_past_due > 0 ? r.max_days_past_due : '—'),
      },
      {
        key: 'promise',
        header: 'Promise',
        sortValue: (r) => r.promise?.date ?? null,
        cell: (r) =>
          r.promise ? (
            <div className="whitespace-nowrap">
              <span className="tabular">{formatINRShort(r.promise.amount)}</span>
              <span className="text-muted-foreground"> on {formatDateShort(r.promise.date)}</span>
              {r.lock_status === 'at_risk' && r.locks_on && r.promise.date > r.locks_on && (
                <div className="text-xs text-warn-foreground">After lock date</div>
              )}
            </div>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        key: 'lock_status',
        header: 'Lock',
        sortValue: (r) => ({ locked: 0, at_risk: 1, ok: 2 })[r.lock_status],
        cell: (r) => {
          const rel = released[r.client_id] ?? overlay.releases[r.client_id]
          return (
            <div className="space-y-1">
              <LockChip row={r} />
              {rel && r.lock_status !== 'locked' && (
                <div className="text-xs text-muted-foreground">Released till {formatDateShort(rel.valid_until)}</div>
              )}
            </div>
          )
        },
      },
      {
        key: 'action',
        header: '',
        sortable: false,
        align: 'right',
        cell: (r) =>
          r.lock_status !== 'locked' ? null : isOwner ? (
            <Button size="sm" variant="secondary" onClick={() => setReleasing(r)}>
              <Unlock />
              Release lock
            </Button>
          ) : (
            <Tooltip content="Only the owner can release">
              <span tabIndex={0} className="inline-flex rounded-md" aria-label="Release lock (only the owner can release)">
                <Button size="sm" variant="secondary" disabled>
                  <Unlock />
                  Release lock
                </Button>
              </span>
            </Tooltip>
          ),
      },
    ],
    [isOwner, overlay.releases, released],
  )

  return (
    <QueryState query={q}>
      {(raw) => {
        const data = applyDebtors(raw, overlay)
        // Live mode: reflect a just-released lock until the refetch lands.
        const clients = data.clients.map((c) =>
          released[c.client_id] && c.lock_status === 'locked' ? { ...c, lock_status: 'ok' as const } : c,
        )
        const atRiskWeek = clients
          .filter((c) => c.lock_status === 'at_risk' && c.locks_on && daysBetween(data.as_of, c.locks_on) <= 7)
          .sort((a, b) => (a.locks_on ?? '').localeCompare(b.locks_on ?? ''))
        const rows = filter === 'all' ? clients : clients.filter((c) => c.lock_status === filter)
        const lockedCount = clients.filter((c) => c.lock_status === 'locked').length
        const atRiskCount = clients.filter((c) => c.lock_status === 'at_risk').length

        return (
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
              <Card className="xl:col-span-2">
                <CardHeader title="Ageing" description={`As of ${formatDate(data.as_of)} · days past due date`} />
                <CardContent className="space-y-5">
                  <AgeingBar buckets={data.totals.buckets} height="h-5" showLegend />
                  <div className="grid grid-cols-2 gap-4 border-t border-border pt-4 sm:grid-cols-4">
                    <Stat label="Outstanding" value={formatINRShort(data.totals.outstanding)} />
                    <Stat label="Overdue" value={formatINRShort(data.totals.overdue)} tone="danger" />
                    <Stat label="At lock risk" value={formatINRShort(data.totals.at_risk)} tone="warn" />
                    <Stat label="Locked" value={formatINRShort(data.totals.locked)} hint={`${lockedCount} client(s)`} />
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader
                  title="At risk this week"
                  description={`Locks when unpaid past due + ${data.grace_days} days`}
                  actions={<CalendarClock className="size-4 text-muted-foreground" aria-hidden />}
                />
                <CardContent className="pt-3">
                  {atRiskWeek.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No client will lock in the next 7 days.</p>
                  ) : (
                    <ul className="divide-y divide-border">
                      {atRiskWeek.map((c) => {
                        const days = daysBetween(data.as_of, c.locks_on!)
                        const late = c.promise && c.promise.date > c.locks_on!
                        return (
                          <li key={c.client_id} className="py-2.5">
                            <div className="flex items-center justify-between gap-3">
                              <span className="truncate font-medium text-foreground">{c.client_name}</span>
                              <StatusChip tone={days <= 2 ? 'danger' : 'warn'}>
                                {days <= 0 ? 'Today' : days === 1 ? 'Tomorrow' : `In ${days} days`}
                              </StatusChip>
                            </div>
                            <div className="tabular mt-0.5 text-xs text-muted-foreground">
                              {formatINRShort(c.outstanding)} · locks {formatDateShort(c.locks_on)}
                              {c.promise ? ` · promised ${formatDateShort(c.promise.date)}` : ' · no promise'}
                            </div>
                            {late && (
                              <div className="mt-1 flex items-center gap-1 text-xs text-warn-foreground">
                                <AlertTriangle className="size-3" aria-hidden /> Promise is after the lock date
                              </div>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-foreground">Clients</h2>
              <Segmented<Filter>
                aria-label="Filter clients"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: 'all', label: `All ${clients.length}` },
                  { value: 'at_risk', label: `At risk ${atRiskCount}` },
                  { value: 'locked', label: `Locked ${lockedCount}` },
                ]}
              />
            </div>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.client_id}
              defaultSort={{ key: 'lock_status', dir: 'asc' }}
              empty={<EmptyState compact title="No clients here" description="Nothing matches this filter." />}
            />
            {!isOwner && lockedCount > 0 && (
              <p className="text-xs text-muted-foreground">Only the owner can release a client lock. Each release is logged with time.</p>
            )}

            <ReleaseDialog
              row={releasing}
              onClose={() => setReleasing(null)}
              onReleased={(res) => {
                if (isMock) moneyStore.release(res)
                else {
                  setReleased((m) => ({ ...m, [res.client_id]: res }))
                  q.refetch()
                }
              }}
            />
          </div>
        )
      }}
    </QueryState>
  )
}

function ReleaseDialog({
  row,
  onClose,
  onReleased,
}: {
  row: DebtorRow | null
  onClose: () => void
  onReleased: (r: ReleaseLockResult) => void
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!row) return
    setBusy(true)
    try {
      const res = await api.post<ReleaseLockResult>(`/api/clients/${row.client_id}/release-lock`, { reason: reason.trim() })
      const result: ReleaseLockResult = isMock
        ? { ...res, client_id: row.client_id, lock_status: 'ok', reason: reason.trim() }
        : res
      onReleased(result)
      toast.success(`Lock released for ${row.client_name}`, {
        description: `Valid until ${formatDate(result.valid_until)}. Logged as ${result.audit_id}.`,
      })
      setReason('')
      onClose()
    } catch (e) {
      toast.error('Could not release the lock', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={!!row} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Release lock for {row?.client_name}?</DialogTitle>
          <DialogDescription>
            {row && (
              <>
                {formatINR(row.outstanding)} is outstanding, {row.max_days_past_due} days past due. Releasing lets
                dispatch and new jobs continue. The lock comes back automatically if the bills stay unpaid.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <Field label="Reason (saved in the audit log)" htmlFor="release-reason">
          <Textarea
            id="release-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. RTGS of ₹1,00,000 confirmed by bank; balance by 30-Nov"
          />
        </Field>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy} disabled={reason.trim().length < 3}>
            <Unlock />
            Release lock
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
