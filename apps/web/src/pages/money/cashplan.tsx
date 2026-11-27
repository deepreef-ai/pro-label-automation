import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle } from 'lucide-react'
import type { CashPlan } from '@contract/types'
import { Card, CardContent, CardHeader, QueryState, StatusChip } from '@/components/ui'
import { useApi } from '@/lib/api'
import { formatCompact, formatINRShort, formatMonth } from '@/lib/format'
import { cn } from '@/lib/utils'

interface Row {
  month: string
  label: string
  inflow: number
  outflow: number
  gap: number
  opening: number
  closing: number
  low: boolean
}

function toRows(p: CashPlan): Row[] {
  return p.months.map((m) => {
    const outflow = m.outflow_suppliers + m.outflow_salaries + m.outflow_overheads + m.outflow_gst + m.outflow_other
    return {
      month: m.month,
      label: formatMonth(m.month).replace(/ (\d{2})(\d{2})$/, " '$2"),
      inflow: m.inflow_collections,
      outflow,
      gap: m.inflow_collections - outflow,
      opening: m.opening,
      closing: m.closing,
      low: m.low_cash,
    }
  })
}

function CashTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  return (
    <div className="min-w-44 rounded-md border border-border bg-surface px-3 py-2 text-sm shadow-md">
      <div className="mb-1 font-semibold text-foreground">{formatMonth(r.month)}</div>
      <div className="tabular space-y-0.5 text-muted-foreground">
        <div className="flex justify-between gap-4">
          <span>In</span>
          <span className="text-foreground">{formatINRShort(r.inflow)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Out</span>
          <span className="text-foreground">{formatINRShort(r.outflow)}</span>
        </div>
        <div className="flex justify-between gap-4 border-t border-border pt-0.5">
          <span>Gap</span>
          <span className={cn('font-medium', r.gap < 0 ? 'text-danger-foreground' : 'text-ok-foreground')}>
            {formatINRShort(r.gap)}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Closing cash</span>
          <span className="text-foreground">{formatINRShort(r.closing)}</span>
        </div>
      </div>
    </div>
  )
}

export function CashPlanTab() {
  const q = useApi<CashPlan>('/api/cashplan')
  return (
    <QueryState query={q} isEmpty={(d) => d.months.length === 0}>
      {(plan) => {
        const rows = toRows(plan)
        const negatives = rows.filter((r) => r.gap < 0)
        return (
          <div className="space-y-5">
            {negatives.length > 0 && (
              <div className="flex items-start gap-2.5 rounded-lg border border-danger/20 bg-danger-soft px-4 py-3 text-sm text-danger-foreground">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  More money goes out than comes in during{' '}
                  <strong>{negatives.map((r) => formatMonth(r.month)).join(', ')}</strong>. Cash dips below the{' '}
                  {formatINRShort(plan.min_cash)} minimum in {rows.filter((r) => r.low).length} month(s).
                </span>
              </div>
            )}
            <Card>
              <CardHeader
                title="Next 6 months: money in vs out"
                description="Bars show collections and all payments; the line is the monthly gap (in − out). Shaded months are negative."
              />
              <CardContent>
                <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <span className="size-2.5 rounded-sm bg-chart-1" aria-hidden /> Money in
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="size-2.5 rounded-sm bg-chart-3" aria-hidden /> Money out
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-0.5 w-4 rounded-full bg-foreground" aria-hidden /> Gap
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="size-2.5 rounded-sm bg-danger-soft ring-1 ring-danger/30" aria-hidden /> Negative month
                  </span>
                </div>
                <div className="h-80 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="28%">
                      <CartesianGrid vertical={false} stroke="var(--border)" />
                      {rows.map((r) =>
                        r.gap < 0 ? (
                          <ReferenceArea key={r.month} x1={r.label} x2={r.label} fill="var(--danger-soft)" fillOpacity={1} ifOverflow="extendDomain" />
                        ) : null,
                      )}
                      <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: 'var(--border)' }} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
                      <YAxis
                        tickLine={false}
                        axisLine={false}
                        width={56}
                        tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
                        tickFormatter={(v: number) => `₹${formatCompact(v)}`}
                      />
                      <ReferenceLine y={0} stroke="var(--border-strong)" />
                      <ChartTooltip content={<CashTooltip />} cursor={{ fill: 'var(--surface-muted)', opacity: 0.6 }} />
                      <Bar dataKey="inflow" name="Money in" fill="var(--chart-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                      <Bar dataKey="outflow" name="Money out" fill="var(--chart-3)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                      <Line
                        dataKey="gap"
                        name="Gap"
                        type="monotone"
                        stroke="var(--foreground)"
                        strokeWidth={2}
                        dot={{ r: 4, fill: 'var(--surface)', strokeWidth: 2 }}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <div className="overflow-x-auto rounded-lg border border-border bg-surface">
              <table className="w-full text-base">
                <thead>
                  <tr className="bg-surface-muted text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 text-left font-medium">Month</th>
                    <th className="px-4 py-2.5 text-right font-medium">Opening</th>
                    <th className="px-4 py-2.5 text-right font-medium">In</th>
                    <th className="px-4 py-2.5 text-right font-medium">Out</th>
                    <th className="px-4 py-2.5 text-right font-medium">Gap</th>
                    <th className="px-4 py-2.5 text-right font-medium">Closing</th>
                    <th className="px-4 py-2.5 text-left font-medium">Cash</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {rows.map((r) => (
                    <tr key={r.month} className={cn('border-t border-border', r.gap < 0 && 'bg-danger-soft/60')}>
                      <td className="px-4 py-2.5 font-medium">{formatMonth(r.month)}</td>
                      <td className="px-4 py-2.5 text-right">{formatINRShort(r.opening)}</td>
                      <td className="px-4 py-2.5 text-right">{formatINRShort(r.inflow)}</td>
                      <td className="px-4 py-2.5 text-right">{formatINRShort(r.outflow)}</td>
                      <td className={cn('px-4 py-2.5 text-right font-medium', r.gap < 0 ? 'text-danger-foreground' : 'text-ok-foreground')}>
                        {formatINRShort(r.gap)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium">{formatINRShort(r.closing)}</td>
                      <td className="px-4 py-2.5">
                        {r.low ? (
                          <StatusChip tone="warn">Below {formatINRShort(plan.min_cash)}</StatusChip>
                        ) : (
                          <StatusChip tone="ok">OK</StatusChip>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      }}
    </QueryState>
  )
}
