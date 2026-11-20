import { useMemo } from 'react'
import { ArrowRight, CalendarCheck2, FileWarning, IndianRupee, PackageCheck, PackageMinus, PackagePlus } from 'lucide-react'
import type { DataQuality, StockResponse, StoreSummary } from '@contract/types'
import { useApi } from '@/lib/api'
import { formatDate, formatINRShort, formatMonth, formatNumber, formatPercent, parseDate } from '@/lib/format'
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  KpiCard,
  QueryState,
  Skeleton,
  StatusChip,
  toneForStatus,
} from '@/components/ui'
import { BarRow, daysBetween, InlineAlert } from './common'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** `2026-06-04` -> `4 Jun` */
function dayMonth(iso: string | null): string {
  const d = parseDate(iso)
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()]}` : 'blank'
}

export function OverviewTab({ onOpenTab }: { onOpenTab: (tab: string) => void }) {
  const summary = useApi<StoreSummary>('/api/store/summary')
  const stock = useApi<StockResponse>('/api/store/stock')

  return (
    <div className="space-y-6">
      <QueryState query={summary} loading={<KpiSkeletonRow />}>
        {(s) => (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="Stock value" value={s.stock_value} icon={IndianRupee} deltaLabel={`as of ${formatDate(s.as_of)}`} />
            <KpiCard
              label={`Received in ${formatMonth(s.month)}`}
              value={s.groups.reduce((a, g) => a + g.received_value_month, 0)}
              icon={PackagePlus}
              deltaLabel={`${formatNumber(s.grns_month)} GRNs`}
            />
            <KpiCard
              label={`Issued in ${formatMonth(s.month)}`}
              value={s.groups.reduce((a, g) => a + g.issued_value_month, 0)}
              icon={PackageMinus}
              deltaLabel={`${formatNumber(s.issues_month)} issue lines`}
            />
            <KpiCard
              label="Issued without job card"
              value={formatPercent(s.issue_lines_without_jc_pct)}
              icon={FileWarning}
              deltaLabel={`${formatINRShort(s.groups.reduce((a, g) => a + g.issued_without_jc_value_month, 0))} this month`}
            />
          </div>
        )}
      </QueryState>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title="Stock value by group" description="Opening + received − issued, valued at item rate." />
          <CardContent>
            <QueryState query={summary} loading={<ListSkeleton />}>
              {(s) => <GroupBars summary={s} />}
            </QueryState>
          </CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader title="Stock ageing" description="Days since the last receipt or issue per item." />
          <CardContent>
            <QueryState query={stock} loading={<ListSkeleton />}>
              {(st) => <Ageing stock={st} />}
            </QueryState>
          </CardContent>
        </Card>
      </div>

      <DataQualityPanel onOpenTab={onOpenTab} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Below minimum stock"
            description="Items under their minimum level, or short for open jobs."
            actions={
              <button
                type="button"
                onClick={() => onOpenTab('stock')}
                className="inline-flex items-center gap-1 rounded-sm text-sm font-medium text-accent hover:underline"
              >
                All stock <ArrowRight className="size-3.5" aria-hidden />
              </button>
            }
          />
          <CardContent>
            <QueryState query={stock} loading={<ListSkeleton />}>
              {(st) => <BelowMin stock={st} />}
            </QueryState>
          </CardContent>
        </Card>
        <Card>
          <CardHeader title="Shortages for open jobs" description="Planned metres the store cannot cover today." />
          <CardContent>
            <QueryState query={summary} loading={<ListSkeleton />}>
              {(s) =>
                s.shortages.length === 0 ? (
                  <EmptyState compact icon={PackageCheck} title="No shortages" description="Every open job is covered." />
                ) : (
                  <ul className="divide-y divide-border">
                    {s.shortages.map((n) => (
                      <li key={n.item_id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="font-medium text-foreground">{n.material}</span>
                          <StatusChip tone="danger" size="sm">
                            Short
                          </StatusChip>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {n.jobs.map((j) => `${j.job_card} (${formatNumber(j.need_m)} m)`).join(' · ')}
                        </p>
                      </li>
                    ))}
                  </ul>
                )
              }
            </QueryState>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function GroupBars({ summary }: { summary: StoreSummary }) {
  const max = Math.max(...summary.groups.map((g) => g.stock_value), 1)
  const tones = ['accent', 'blue', 'amber', 'green', 'grey'] as const
  return (
    <div className="space-y-4">
      {summary.groups.map((g, i) => (
        <BarRow
          key={g.group}
          label={g.group}
          value={g.stock_value}
          max={max}
          tone={tones[i % tones.length]}
          display={formatINRShort(g.stock_value)}
          hint={`In ${formatINRShort(g.received_value_month)} · Out ${formatINRShort(g.issued_value_month)}${
            g.issued_without_jc_value_month > 0 ? ` · ${formatINRShort(g.issued_without_jc_value_month)} without job card` : ''
          }`}
        />
      ))}
      <p className="border-t border-border pt-3 text-xs text-muted-foreground">
        Customer-owned party laminate is not included. Opening stock counted from {formatDate(summary.stock_from)}.
      </p>
    </div>
  )
}

function Ageing({ stock }: { stock: StockResponse }) {
  const buckets = useMemo(() => {
    const b = { moving: { n: 0, v: 0 }, slow: { n: 0, v: 0 }, non: { n: 0, v: 0 } }
    for (const it of stock.items) {
      // The real ERP import has items issued beyond opening + received (negative stock). They hold no
      // stock to age and would turn the bars negative, so only items with stock on hand count here.
      if (!(it.value > 0)) continue
      const days = daysBetween(it.last_movement, stock.as_of)
      const key = it.status === 'non_moving' || days > 90 ? 'non' : days > 30 ? 'slow' : 'moving'
      b[key].n += 1
      b[key].v += it.value
    }
    return b
  }, [stock])
  const total = buckets.moving.v + buckets.slow.v + buckets.non.v || 1
  const rows = [
    { key: 'moving', label: 'Moving (≤ 30 days)', tone: 'green' as const, ...buckets.moving },
    { key: 'slow', label: 'Slow (31–90 days)', tone: 'amber' as const, ...buckets.slow },
    { key: 'non', label: 'Non-moving (> 90 days)', tone: 'danger' as const, ...buckets.non },
  ]
  return (
    <div className="space-y-5">
      <div className="flex h-3 overflow-hidden rounded-full bg-surface-sunken" role="img" aria-label="Stock value split by age">
        {rows.map((r) => (
          <div
            key={r.key}
            className={r.tone === 'green' ? 'bg-chart-4' : r.tone === 'amber' ? 'bg-chart-3' : 'bg-danger'}
            style={{ width: `${(r.v / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="space-y-4">
        {rows.map((r) => (
          <BarRow
            key={r.key}
            label={`${r.label} · ${r.n} item${r.n === 1 ? '' : 's'}`}
            value={r.v}
            max={total}
            tone={r.tone}
            display={`${formatINRShort(r.v)} · ${formatPercent(r.v / total, { digits: 0 })}`}
          />
        ))}
      </div>
    </div>
  )
}

function BelowMin({ stock }: { stock: StockResponse }) {
  const all = stock.items.filter((i) => i.stock < i.min_stock || i.status === 'low' || i.status === 'short')
  // The real item master has well over a hundred items below minimum: show the worst first, capped.
  const rows = [...all].sort((a, b) => rank(a) - rank(b) || a.stock - a.min_stock - (b.stock - b.min_stock)).slice(0, BELOW_MIN_SHOWN)
  if (rows.length === 0)
    return <EmptyState compact icon={PackageCheck} title="All items above minimum" description="Nothing to reorder today." />
  return (
    <ul className="divide-y divide-border">
      {rows.map((r) => (
        <li key={r.item_id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <p className="truncate font-medium text-foreground">{r.item_name}</p>
            <p className="tabular text-sm text-muted-foreground">
              {formatNumber(r.stock, 2)} {r.uom} in stock · minimum {formatNumber(r.min_stock)} {r.uom}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <StatusChip tone={toneForStatus(r.status === 'low' ? 'low_stock' : r.status)} size="sm">
              {r.status === 'low' ? 'Low' : r.status === 'short' ? 'Short' : 'Below min'}
            </StatusChip>
            <span className="tabular text-xs text-muted-foreground">
              need {formatNumber(Math.max(0, r.min_stock - r.stock), 2)} {r.uom}
            </span>
          </div>
        </li>
      ))}
      {all.length > rows.length && (
        <li className="pt-3 text-sm text-muted-foreground">
          and {formatNumber(all.length - rows.length)} more items below minimum (see All stock)
        </li>
      )}
    </ul>
  )
}

const BELOW_MIN_SHOWN = 10
const rank = (i: StockResponse['items'][number]) => (i.status === 'short' ? 0 : i.status === 'low' ? 1 : 2)

function DataQualityPanel({ onOpenTab }: { onOpenTab: (tab: string) => void }) {
  const q = useApi<DataQuality>('/api/store/data-quality')
  return (
    <Card>
      <CardHeader
        title="Data quality of the ERP import"
        description="What we found when we read the old ERP issue and GRN exports."
        actions={<Badge tone="info">Import check</Badge>}
      />
      <CardContent>
        <QueryState query={q} loading={<ListSkeleton />}>
          {(dq) => (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="space-y-4">
                <div className="rounded-lg border border-danger/20 bg-danger-soft p-4">
                  <p className="tabular text-3xl font-semibold tracking-tight text-danger-foreground">
                    {formatPercent(dq.pct_without_jc, { digits: 0 })}
                  </p>
                  <p className="mt-1 font-medium text-danger-foreground">
                    {formatPercent(dq.pct_without_jc, { digits: 0 })} of issue lines had no job card
                  </p>
                  <p className="mt-1 text-sm text-danger-foreground/90">
                    {formatNumber(dq.issue_lines_without_jc)} of {formatNumber(dq.issue_lines)} lines ·{' '}
                    {formatINRShort(dq.value_without_jc)} of material that cannot be charged to a job.
                    {` ${formatDate(dq.period_from)} – ${formatDate(dq.period_to)}.`}
                  </p>
                  <button
                    type="button"
                    onClick={() => onOpenTab('issues')}
                    className="mt-3 inline-flex items-center gap-1 rounded-sm text-sm font-medium text-danger-foreground underline-offset-2 hover:underline"
                  >
                    New issues now require a job card <ArrowRight className="size-3.5" aria-hidden />
                  </button>
                </div>
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {dq.checks.map((c) => (
                    <li key={c.key} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-foreground">{c.label}</p>
                        <p className="tabular text-xs text-muted-foreground">
                          {formatNumber(c.count)} rows
                          {c.pct !== null && ` · ${formatPercent(c.pct)}`}
                          {c.value !== null && ` · ${formatINRShort(c.value)}`}
                        </p>
                      </div>
                      <StatusChip tone={toneForStatus(c.severity)} size="sm">
                        {c.severity}
                      </StatusChip>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-4" id="dates">
                <div className="flex items-start gap-3">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent-soft-foreground">
                    <CalendarCheck2 className="size-4" aria-hidden />
                  </div>
                  <div>
                    <p className="font-medium text-foreground">
                      {formatNumber(dq.date_fixes.count)} ERP dates fixed to day-first
                    </p>
                    <p className="text-sm text-muted-foreground">
                      The ERP writes dates as dd-mm-yy text. Excel read many of them month-first. We always read the day
                      first.
                    </p>
                  </div>
                </div>
                <InlineAlert tone="info" title="Example">
                  <span className="font-mono">06-04-26</span>: Excel read <s>4 Jun</s> → fixed <strong>6 Apr</strong>
                </InlineAlert>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-surface-muted text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-left font-medium">ERP doc</th>
                        <th className="px-3 py-2 text-left font-medium">Raw text</th>
                        <th className="px-3 py-2 text-left font-medium">Excel read (before)</th>
                        <th className="px-3 py-2 text-left font-medium">Fixed (after)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dq.date_fixes.examples.map((ex) => (
                        <tr key={ex.source_row} className="border-t border-border">
                          <td className="px-3 py-2">
                            <span className="text-foreground">{ex.doc_no}</span>
                            <span className="block text-xs text-muted-foreground">row {ex.source_row}</span>
                          </td>
                          <td className="px-3 py-2 font-mono text-foreground">{ex.raw}</td>
                          <td className="px-3 py-2 text-danger-foreground">
                            {ex.excel_read_as ? <s>{dayMonth(ex.excel_read_as)}</s> : <span>not read as a date</span>}
                          </td>
                          <td className="px-3 py-2 font-medium text-ok-foreground">{formatDate(ex.fixed_to)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-muted-foreground">Source: {dq.source}</p>
              </div>
            </div>
          )}
        </QueryState>
      </CardContent>
    </Card>
  )
}

function KpiSkeletonRow() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <KpiCard key={i} label=" " value={0} loading />
      ))}
    </div>
  )
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-4" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="h-2 w-full" />
        </div>
      ))}
    </div>
  )
}
