import { useMemo, useState } from 'react'
import { ArrowRight, Droplets, Scissors } from 'lucide-react'
import type { InkAllocation, Item, PartyLaminateResponse, Roll, Slitting, StockResponse, StockRow } from '@contract/types'
import { useApi } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatMonth, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  type Column,
  DataTable,
  DemoBadge,
  EmptyState,
  Input,
  KpiCard,
  QueryState,
  Segmented,
  StatusChip,
  TableSkeleton,
  toneForStatus,
} from '@/components/ui'
import { BarcodeId, BarRow, InlineAlert, Stat } from './common'

/* ------------------------------------------------------------------ */
/* Stock                                                               */
/* ------------------------------------------------------------------ */

const STATUS_LABEL: Record<StockRow['status'], string> = { ok: 'OK', low: 'Low', short: 'Short', non_moving: 'Non-moving' }

export function StockTab() {
  const q = useApi<StockResponse>('/api/store/stock')
  const items = useApi<Item[]>('/api/items')
  const [counts, setCounts] = useState<Record<string, string>>({})

  const headOf = useMemo(() => {
    const m = new Map<string, string>()
    for (const i of items.data ?? []) m.set(i.id, i.stock_head)
    return m
  }, [items.data])

  const columns: Column<StockRow>[] = [
    {
      key: 'item_name',
      header: 'Item',
      cell: (r) => (
        <div>
          <p className="font-medium">{r.item_name}</p>
          <p className="text-xs text-muted-foreground">
            {r.item_id} · {headOf.get(r.item_id) ?? r.group}
          </p>
        </div>
      ),
    },
    { key: 'opening', header: 'Opening', align: 'right', cell: (r) => formatNumber(r.opening, 2) },
    { key: 'received', header: 'Received', align: 'right', cell: (r) => formatNumber(r.received, 2) },
    { key: 'issued', header: 'Issued', align: 'right', cell: (r) => formatNumber(r.issued, 2) },
    {
      key: 'stock',
      header: 'Book stock',
      align: 'right',
      cell: (r) => (
        <div>
          <p className="font-medium">
            {formatNumber(r.stock, 2)} {r.uom}
          </p>
          {r.stock_sqm !== null && <p className="text-xs text-muted-foreground">{formatNumber(r.stock_sqm, 1)} sq m</p>}
        </div>
      ),
    },
    {
      key: 'physical',
      header: 'Physical count',
      sortable: false,
      width: 'w-36',
      cell: (r) => (
        <Input
          inputSize="sm"
          type="number"
          inputMode="decimal"
          aria-label={`Physical count for ${r.item_name}`}
          placeholder={formatNumber(r.stock, 2)}
          value={counts[r.item_id] ?? ''}
          onChange={(e) => setCounts((c) => ({ ...c, [r.item_id]: e.target.value }))}
          className="tabular text-right"
        />
      ),
    },
    {
      key: 'diff',
      header: 'Difference',
      align: 'right',
      sortable: false,
      cell: (r) => {
        const raw = counts[r.item_id]
        if (raw === undefined || raw === '') return <span className="text-muted-foreground">—</span>
        const d = Number(raw) - r.stock
        const val = d * r.rate * (r.stock_sqm !== null && r.stock ? r.stock_sqm / r.stock : 1)
        return (
          <div className={cn(d < 0 ? 'text-danger-foreground' : d > 0 ? 'text-ok-foreground' : 'text-muted-foreground')}>
            <p className="font-medium">
              {d > 0 ? '+' : ''}
              {formatNumber(d, 2)} {r.uom}
            </p>
            <p className="text-xs">{formatINR(val)}</p>
          </div>
        )
      },
    },
    { key: 'value', header: 'Value', align: 'right', cell: (r) => formatINR(r.value) },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => (
        <StatusChip size="sm" tone={r.status === 'low' ? 'warn' : r.status === 'non_moving' ? 'neutral' : toneForStatus(r.status)}>
          {STATUS_LABEL[r.status]}
        </StatusChip>
      ),
    },
    { key: 'last_movement', header: 'Last move', cell: (r) => formatDate(r.last_movement) },
  ]

  return (
    <QueryState query={q} loading={<TableSkeleton />} isEmpty={(s) => s.items.length === 0}>
      {(s) => {
        const heads = new Map<string, number>()
        for (const r of s.items) {
          const h = headOf.get(r.item_id) ?? r.group
          heads.set(h, (heads.get(h) ?? 0) + r.value)
        }
        const headRows = [...heads.entries()].sort((a, b) => b[1] - a[1])
        const max = headRows[0]?.[1] ?? 1
        const counted = s.items.filter((r) => counts[r.item_id] !== undefined && counts[r.item_id] !== '')
        const countDiffValue = counted.reduce((a, r) => {
          const d = Number(counts[r.item_id]) - r.stock
          return a + d * r.rate * (r.stock_sqm !== null && r.stock ? r.stock_sqm / r.stock : 1)
        }, 0)
        return (
          <div className="space-y-6">
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader title="Value by stock head" description={`Book stock as of ${formatDate(s.as_of)}, opening from ${formatDate(s.stock_from)}.`} />
                <CardContent className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
                  {headRows.map(([h, v]) => (
                    <BarRow key={h} label={h} value={v} max={max} display={formatINRShort(v)} />
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader title="Physical count" description="Type counted quantities in the table to see the difference." />
                <CardContent className="grid grid-cols-2 gap-4">
                  <Stat label="Total book value" value={formatINRShort(s.total_value)} />
                  <Stat label="Items counted" value={`${counted.length} / ${s.items.length}`} />
                  <Stat
                    label="Count difference"
                    value={
                      <span className={cn(countDiffValue < 0 && 'text-danger-foreground', countDiffValue > 0 && 'text-ok-foreground')}>
                        {formatINRShort(countDiffValue)}
                      </span>
                    }
                    sub="at item rate"
                    className="col-span-2"
                  />
                </CardContent>
              </Card>
            </div>
            <DataTable rows={s.items} rowKey={(r) => r.item_id} columns={columns} />
          </div>
        )
      }}
    </QueryState>
  )
}

/* ------------------------------------------------------------------ */
/* Rolls                                                               */
/* ------------------------------------------------------------------ */

type RollFilter = 'all' | 'in_stock' | 'partly_issued' | 'consumed'

export function RollsTab() {
  const q = useApi<Roll[]>('/api/store/rolls')
  const [filter, setFilter] = useState<RollFilter>('all')
  const columns: Column<Roll>[] = [
    {
      key: 'id',
      header: 'Roll',
      cell: (r) => (
        <span className="inline-flex items-center gap-2">
          <BarcodeId id={r.id} /> <DemoBadge show={r.is_demo} />
        </span>
      ),
    },
    { key: 'item_name', header: 'Item' },
    { key: 'width_mm', header: 'Width', align: 'right', cell: (r) => `${r.width_mm} mm` },
    {
      key: 'balance_m',
      header: 'Balance / length',
      align: 'right',
      cell: (r) => (
        <div className="ml-auto w-32">
          <p className="font-medium">
            {formatNumber(r.balance_m)} <span className="text-muted-foreground">/ {formatNumber(r.length_m)} m</span>
          </p>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
            <div className="h-full rounded-full bg-chart-1" style={{ width: `${r.length_m ? (r.balance_m / r.length_m) * 100 : 0}%` }} />
          </div>
        </div>
      ),
    },
    {
      key: 'source',
      header: 'Source',
      cell: (r) => (
        <div>
          <p className="capitalize">{r.source === 'slit' ? 'Slitting' : r.source === 'grn' ? 'GRN' : 'Opening'}</p>
          <p className="text-xs text-muted-foreground">{r.source_ref}</p>
        </div>
      ),
    },
    { key: 'received_on', header: 'Received', cell: (r) => formatDate(r.received_on) },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => (
        <StatusChip size="sm" tone={r.status === 'in_stock' ? 'ok' : r.status === 'partly_issued' ? 'info' : 'neutral'}>
          {r.status === 'in_stock' ? 'In stock' : r.status === 'partly_issued' ? 'Partly issued' : 'Consumed'}
        </StatusChip>
      ),
    },
    {
      key: 'issued_to',
      header: 'Jobs',
      sortable: false,
      cell: (r) => (r.issued_to.length ? r.issued_to.join(', ') : <span className="text-muted-foreground">—</span>),
    },
    { key: 'location', header: 'Location' },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">Every paper and film roll has a permanent barcode ID (R-YYYY-####).</p>
        <Segmented
          aria-label="Filter rolls"
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'All' },
            { value: 'in_stock', label: 'In stock' },
            { value: 'partly_issued', label: 'Partly issued' },
            { value: 'consumed', label: 'Consumed' },
          ]}
        />
      </div>
      <QueryState query={q} loading={<TableSkeleton />}>
        {(rows) => (
          <DataTable rows={filter === 'all' ? rows : rows.filter((r) => r.status === filter)} columns={columns} dense />
        )}
      </QueryState>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Slitting                                                            */
/* ------------------------------------------------------------------ */

export function SlittingTab() {
  const q = useApi<Slitting[]>('/api/store/slitting')
  return (
    <QueryState
      query={q}
      loading={<TableSkeleton />}
      isEmpty={(r) => r.length === 0}
      empty={<EmptyState icon={Scissors} title="No slitting yet" description="Jumbo rolls slit into job widths appear here." />}
    >
      {(rows) => (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">Jumbo rolls slit into job widths. Trim above 5% of the jumbo width is flagged.</p>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {rows.map((s) => (
              <Card key={s.id}>
                <CardHeader
                  title={
                    <span className="inline-flex items-center gap-2">
                      {s.id} <DemoBadge show={s.is_demo} />
                    </span>
                  }
                  description={`${formatDate(s.date)} · ${s.item_name} · ${s.operator}`}
                  actions={
                    <StatusChip tone={s.trim_flag ? 'danger' : 'ok'} size="sm">
                      Trim {formatPercent(s.trim_pct)}
                    </StatusChip>
                  }
                />
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <div className="rounded-md border border-border bg-surface-muted px-3 py-2">
                      <p className="text-xs text-muted-foreground">Jumbo</p>
                      <p className="font-mono">{s.jumbo_roll_id}</p>
                      <p className="tabular text-xs text-muted-foreground">
                        {s.jumbo_width_mm} mm × {formatNumber(s.length_m)} m
                      </p>
                    </div>
                    <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
                    {s.outputs.map((o) => (
                      <div key={o.width_mm} className="rounded-md border border-border px-3 py-2">
                        <p className="text-xs text-muted-foreground">
                          {o.count} × {o.width_mm} mm
                        </p>
                        <p className="font-mono text-xs">{o.roll_ids.join(', ')}</p>
                      </div>
                    ))}
                  </div>
                  {/* Width diagram: outputs + trim */}
                  <div className="flex h-7 overflow-hidden rounded-md border border-border" role="img" aria-label={`Used ${s.used_width_mm} mm, trim ${s.trim_mm} mm`}>
                    {s.outputs.flatMap((o) =>
                      Array.from({ length: o.count }).map((_, i) => (
                        <div
                          key={`${o.width_mm}-${i}`}
                          className="flex items-center justify-center border-r border-surface bg-accent-soft text-2xs text-accent-soft-foreground"
                          style={{ width: `${(o.width_mm / s.jumbo_width_mm) * 100}%` }}
                        >
                          {o.width_mm}
                        </div>
                      )),
                    )}
                    <div
                      className={cn('flex items-center justify-center text-2xs', s.trim_flag ? 'bg-danger-soft text-danger-foreground' : 'bg-warn-soft text-warn-foreground')}
                      style={{ width: `${(s.trim_mm / s.jumbo_width_mm) * 100}%`, minWidth: 18 }}
                      title={`Trim ${s.trim_mm} mm`}
                    >
                      {s.trim_mm}
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-4">
                    <Stat label="Used width" value={`${s.used_width_mm} mm`} />
                    <Stat label="Trim" value={`${s.trim_mm} mm`} />
                    <Stat label="Trim value" value={formatINR(s.trim_value)} />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </QueryState>
  )
}

/* ------------------------------------------------------------------ */
/* Party laminate                                                      */
/* ------------------------------------------------------------------ */

export function PartyLaminateTab() {
  const q = useApi<PartyLaminateResponse>('/api/store/party-laminate')
  return (
    <QueryState query={q} loading={<TableSkeleton />}>
      {(d) => (
        <div className="space-y-6">
          <InlineAlert tone="info" title="Customer-owned material">
            Party laminate belongs to the client. It is tracked in metres only and is excluded from our stock value.
          </InlineAlert>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {d.balances.map((b) => (
              <Card key={`${b.client_id}-${b.laminate}`} className="p-5">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-muted-foreground">{b.client_name}</p>
                  <Badge tone="neutral" size="sm">
                    Not our stock
                  </Badge>
                </div>
                <p className="tabular mt-3 text-3xl font-semibold tracking-tight text-foreground">{formatNumber(b.balance_m)} m</p>
                <p className="mt-1 text-sm text-muted-foreground">{b.laminate}</p>
              </Card>
            ))}
          </div>
          <DataTable
            rows={d.rows}
            defaultSort={{ key: 'date', dir: 'desc' }}
            columns={[
              {
                key: 'id',
                header: 'Entry',
                cell: (r) => (
                  <span className="inline-flex items-center gap-2 font-medium">
                    {r.id} <DemoBadge show={r.is_demo} />
                  </span>
                ),
              },
              { key: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
              { key: 'client_name', header: 'Client' },
              {
                key: 'movement',
                header: 'Movement',
                cell: (r) => (
                  <StatusChip size="sm" tone={r.movement === 'in' ? 'info' : 'neutral'}>
                    {r.movement === 'in' ? 'Received' : 'Used'}
                  </StatusChip>
                ),
              },
              { key: 'laminate', header: 'Laminate', cell: (r) => `${r.laminate} · ${r.width_mm} mm` },
              {
                key: 'qty_m',
                header: 'Qty',
                align: 'right',
                cell: (r) => `${r.movement === 'in' ? '+' : '−'}${formatNumber(r.qty_m)} m`,
              },
              { key: 'job_card', header: 'Job card', cell: (r) => r.job_card ?? '—' },
              { key: 'balance_m', header: 'Balance', align: 'right', cell: (r) => `${formatNumber(r.balance_m)} m` },
            ]}
          />
        </div>
      )}
    </QueryState>
  )
}

/* ------------------------------------------------------------------ */
/* Ink allocation                                                      */
/* ------------------------------------------------------------------ */

export function InkTab() {
  const q = useApi<InkAllocation>('/api/store/ink-allocation')
  return (
    <QueryState query={q} loading={<TableSkeleton />}>
      {(d) => {
        const maxShare = Math.max(...d.rows.map((r) => r.share_pct), 0.01)
        return (
          <div className="space-y-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <KpiCard label={`Ink pool · ${formatMonth(d.month)}`} value={d.pool_value} icon={Droplets} deltaLabel="ink & varnish issued without job card" />
              <KpiCard label="Estimated ink for jobs" value={d.estimate_value} deltaLabel="from press setup estimates" />
              <KpiCard
                label="Pool vs estimate"
                value={formatPercent(d.variance_pct, { signed: true })}
                footer={
                  <StatusChip tone={d.ink_flag ? 'danger' : 'ok'} size="sm">
                    {d.ink_flag ? 'Outside ±20% tolerance' : 'Within ±20% tolerance'}
                  </StatusChip>
                }
              />
            </div>
            <Card>
              <CardHeader title="Shared to jobs" description="The pool is split across this month's jobs in proportion to their estimated ink." />
              <CardContent>
                {d.rows.length === 0 ? (
                  <EmptyState compact title="No jobs to share with" />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs text-muted-foreground">
                          <th className="pb-2 font-medium">Job card</th>
                          <th className="pb-2 font-medium">Client</th>
                          <th className="pb-2 text-right font-medium">Est. ink</th>
                          <th className="w-1/3 min-w-40 pb-2 pl-6 font-medium">Share</th>
                          <th className="pb-2 text-right font-medium">Allocated</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.rows.map((r) => (
                          <tr key={r.job_card} className="border-t border-border">
                            <td className="py-2.5 font-medium text-foreground">{r.job_card}</td>
                            <td className="py-2.5 text-foreground">{r.client_name}</td>
                            <td className="tabular py-2.5 text-right">{formatNumber(r.est_ink_kg, 2)} kg</td>
                            <td className="py-2.5 pl-6">
                              <div className="flex items-center gap-2">
                                <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                                  <div className="h-full rounded-full bg-chart-2" style={{ width: `${(r.share_pct / maxShare) * 100}%` }} />
                                </div>
                                <span className="tabular w-12 text-right">{formatPercent(r.share_pct)}</span>
                              </div>
                            </td>
                            <td className="tabular py-2.5 text-right font-medium">{formatINR(r.allocated_value)}</td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr className="border-t border-border-strong">
                          <td colSpan={4} className="pt-2.5 text-muted-foreground">
                            Total allocated
                          </td>
                          <td className="tabular pt-2.5 text-right font-semibold">
                            {formatINR(d.rows.reduce((a, r) => a + r.allocated_value, 0))}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )
      }}
    </QueryState>
  )
}
