import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Bot, ChevronRight, Sparkles } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AgentBrief, DashboardSummary } from '@contract/types'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  DataTable,
  DemoBadge,
  EmptyState,
  Skeleton,
  StatusChip,
  TableSkeleton,
  type Column,
  type Tone,
} from '@/components/ui'
import type { UseApiResult } from '@/lib/api'
import {
  formatCompact,
  formatDateShort,
  formatDateTime,
  formatINRShort,
  formatINRWhole,
  formatNumber,
  formatPercent,
  formatRelative,
} from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DashAlert, LowProfitJob, MachineRow, ProfitRiskRow, SummaryExt } from './derive'

export const SEVERITY_TONE: Record<'high' | 'medium' | 'low', Tone> = { high: 'danger', medium: 'warn', low: 'info' }
const SEVERITY_LABEL = { high: 'High', medium: 'Medium', low: 'Low' } as const

/* Shared bits ------------------------------------------------------- */

function SectionError({ query, what }: { query: UseApiResult<unknown>; what: string }) {
  return (
    <EmptyState
      compact
      icon={AlertTriangle}
      title={`Couldn't load ${what}`}
      description={query.error?.message}
      action={
        <Button variant="secondary" size="sm" onClick={query.refetch}>
          Try again
        </Button>
      }
    />
  )
}

function ChartSkeleton({ height }: { height: number }) {
  return (
    <div className="px-5 pb-5" role="status" aria-label="Loading chart">
      <Skeleton className="w-full" style={{ height }} />
    </div>
  )
}

const axisTick = { fill: 'var(--muted-foreground)', fontSize: 12 }
const tooltipStyle = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  boxShadow: 'var(--elev-md)',
  color: 'var(--foreground)',
  fontSize: 13,
}

/* AI morning brief ------------------------------------------------- */

export function BriefCard({ query }: { query: UseApiResult<AgentBrief> }) {
  const brief = query.data
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-4 border-b border-border bg-accent-soft/50 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent-soft-foreground">
            <Sparkles className="size-[18px]" aria-hidden />
          </div>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-muted-foreground">
              <span>AI morning brief</span>
              {brief && (
                <>
                  <span aria-hidden>·</span>
                  <span>{formatDateTime(brief.generated_at)}</span>
                  <Badge size="sm" tone={brief.source === 'llm' ? 'accent' : 'neutral'}>
                    {brief.source === 'llm' ? 'AI written' : 'Template'}
                  </Badge>
                </>
              )}
            </div>
            {brief ? (
              <p className="text-md font-semibold text-foreground">{brief.headline}</p>
            ) : query.loading ? (
              <Skeleton className="h-5 w-96 max-w-full" />
            ) : null}
          </div>
        </div>
        <Button asChild variant="secondary" size="sm" className="shrink-0 self-start">
          <Link to="/agents">
            <Bot aria-hidden />
            Open Agents Center
          </Link>
        </Button>
      </div>
      {query.loading && !brief ? (
        <div className="space-y-3 p-5" role="status" aria-label="Loading brief">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-4 w-full max-w-xl" />
          ))}
        </div>
      ) : query.noData ? (
        <EmptyState compact icon={Sparkles} title="No brief yet" description="The owner brief agent runs at 7:00 every morning." />
      ) : query.error ? (
        <SectionError query={query} what="the brief" />
      ) : brief ? (
        <ul className="grid gap-x-8 px-5 py-3 md:grid-cols-2">
          {brief.items.map((item, i) => {
            const body = (
              <>
                <span
                  className={cn('mt-[7px] size-2 shrink-0 rounded-full', {
                    'bg-danger': item.severity === 'high',
                    'bg-warn': item.severity === 'medium',
                    'bg-info': item.severity === 'low',
                  })}
                  aria-label={`${SEVERITY_LABEL[item.severity]} priority`}
                />
                <span className="min-w-0 flex-1 text-base text-foreground">{item.text}</span>
                {item.link && <ChevronRight className="mt-0.5 size-4 shrink-0 text-subtle-foreground" aria-hidden />}
              </>
            )
            return (
              <li key={i}>
                {item.link ? (
                  <Link
                    to={item.link}
                    className="-mx-2 flex items-start gap-3 rounded-md px-2 py-2.5 transition-colors hover:bg-surface-muted"
                  >
                    {body}
                  </Link>
                ) : (
                  <div className="flex items-start gap-3 py-2.5">{body}</div>
                )}
              </li>
            )
          })}
        </ul>
      ) : null}
    </Card>
  )
}

/* Alerts ------------------------------------------------------------ */

export function AlertsCard({
  query,
  alerts,
  asOf,
  note,
}: {
  query: UseApiResult<unknown>
  alerts: DashAlert[] | undefined
  asOf?: string
  note?: string | null
}) {
  const counts = { high: 0, medium: 0, low: 0 }
  alerts?.forEach((a) => counts[a.severity]++)
  return (
    <Card className="flex min-h-0 flex-col">
      <CardHeader
        title="Alerts"
        description={asOf ? `As of ${formatDateTime(asOf)}` : 'Things that need a decision'}
        actions={
          alerts && alerts.length > 0 ? (
            <div className="flex flex-wrap justify-end gap-1.5">
              {(['high', 'medium', 'low'] as const).map((s) =>
                counts[s] ? (
                  <StatusChip key={s} tone={SEVERITY_TONE[s]} size="sm">
                    {counts[s]} {SEVERITY_LABEL[s].toLowerCase()}
                  </StatusChip>
                ) : null,
              )}
            </div>
          ) : undefined
        }
      />
      {note && <p className="mx-5 mt-3 rounded-md bg-info-soft px-3 py-2 text-sm text-info-foreground">{note}</p>}
      <div className="mt-3 min-h-0 flex-1">
        {query.loading && !alerts ? (
          <TableSkeleton rows={5} columns={2} />
        ) : query.error && !query.noData ? (
          <SectionError query={query} what="alerts" />
        ) : !alerts || alerts.length === 0 ? (
          <EmptyState compact title="All clear" description="No open alerts right now." />
        ) : (
          <ul className="max-h-[460px] divide-y divide-border overflow-y-auto border-t border-border">
            {alerts.map((a) => (
              <li key={a.id}>
                <Link
                  to={a.link}
                  className="flex items-start gap-3 px-5 py-3 transition-colors hover:bg-surface-muted focus-visible:bg-surface-muted"
                >
                  <StatusChip tone={SEVERITY_TONE[a.severity]} size="sm" className="mt-0.5 w-[4.5rem] justify-center">
                    {SEVERITY_LABEL[a.severity]}
                  </StatusChip>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-foreground">{a.title}</span>
                      {a.derived && (
                        <Badge size="sm" tone="accent">
                          New limit
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">{a.detail}</p>
                    <p className="mt-1 text-xs text-subtle-foreground capitalize">
                      {a.area} · {formatRelative(a.created_at)}
                    </p>
                  </div>
                  <ChevronRight className="mt-1 size-4 shrink-0 text-subtle-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

/* Trend chart ------------------------------------------------------- */

const TREND_DESC: Record<DashboardSummary['period'], string> = {
  today: 'Last 7 days',
  month: 'This month, by week',
  year: 'This year, by month',
}

export function TrendCard({ summary, loading }: { summary: SummaryExt | undefined; loading: boolean }) {
  const daily = summary?.trend_30d?.slice(-30)
  const data = daily?.length
    ? daily.map((d) => ({ label: d.label ?? formatDateShort(d.date), revenue: d.revenue, profit: d.profit }))
    : (summary?.trend ?? [])
  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Dispatch & profit"
        description={daily?.length ? 'Last 30 days' : summary ? TREND_DESC[summary.period] : ' '}
      />
      {loading && !summary ? (
        <ChartSkeleton height={280} />
      ) : data.length < 2 ? (
        <EmptyState compact title="Not enough data yet" description="The trend appears after two periods of sales." />
      ) : (
        <div className="h-[300px] px-2 pt-4 pb-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: 'var(--border)' }} />
              <YAxis
                tick={axisTick}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={(v: number) => formatCompact(v)}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={{ color: 'var(--muted-foreground)', marginBottom: 4 }}
                cursor={{ stroke: 'var(--border-strong)' }}
                formatter={(v) => formatINRShort(Number(v), 2)}
              />
              <Legend
                iconType="plainline"
                wrapperStyle={{ fontSize: 13, color: 'var(--muted-foreground)', paddingTop: 8 }}
              />
              <Line
                type="monotone"
                dataKey="revenue"
                name="Sales (dispatch value)"
                stroke="var(--chart-1)"
                strokeWidth={2}
                dot={data.length <= 12 ? { r: 3, fill: 'var(--chart-1)' } : false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="profit"
                name="Profit"
                stroke="var(--chart-2)"
                strokeWidth={2}
                dot={data.length <= 12 ? { r: 3, fill: 'var(--chart-2)' } : false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

/* Top clients ------------------------------------------------------- */

export function TopClientsCard({ summary, loading }: { summary: SummaryExt | undefined; loading: boolean }) {
  const rows = (summary?.top_clients ?? []).slice(0, 10).map((c) => ({
    ...c,
    short: c.client_name.length > 22 ? `${c.client_name.slice(0, 21)}…` : c.client_name,
  }))
  const height = Math.max(200, rows.length * 40 + 24)
  return (
    <Card className="flex flex-col">
      <CardHeader title="Top clients" description="By invoiced sales in the period" />
      {loading && !summary ? (
        <ChartSkeleton height={220} />
      ) : rows.length === 0 ? (
        <EmptyState compact title="No sales yet" description="Clients appear here once invoices are raised." />
      ) : (
        <div className="px-2 pt-3 pb-4" style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 4 }} barCategoryGap={8}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="short"
                width={150}
                tick={{ ...axisTick, fill: 'var(--foreground)' }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ fill: 'var(--surface-muted)' }}
                labelFormatter={(_, p) => (p?.[0]?.payload as { client_name?: string } | undefined)?.client_name ?? ''}
                formatter={(v) => [formatINRShort(Number(v), 2), 'Sales']}
              />
              <Bar
                dataKey="revenue"
                fill="var(--chart-1)"
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
                label={{
                  position: 'right',
                  fill: 'var(--muted-foreground)',
                  fontSize: 12,
                  formatter: (v: unknown) => formatINRShort(Number(v)),
                }}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

/* Lowest-profit jobs ------------------------------------------------ */

const FLAG_LABEL: Record<string, string> = {
  wastage_high: 'High wastage',
  material_variance: 'Material variance',
  overprod: 'Over-production',
  material_short: 'Material short',
  client_locked: 'Client locked',
  qc_hold: 'QC hold',
  late: 'Late',
}

function JobCell({ jc, client, demo }: { jc: string; client: string; demo?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="font-medium text-foreground tabular">{jc}</span>
        <DemoBadge show={demo} />
      </div>
      <div className="truncate text-sm text-muted-foreground">{client}</div>
    </div>
  )
}

export function LowProfitCard({
  jobs,
  riskRows,
  loading,
}: {
  /** Job-wise profit from the API, lowest first (null: the API has none, use the risk fallback). */
  jobs: LowProfitJob[] | null
  riskRows: ProfitRiskRow[] | undefined
  loading: boolean
}) {
  const navigate = useNavigate()
  const fromApi = jobs

  const profitCols: Column<LowProfitJob>[] = [
    { key: 'job_card', header: 'Job', cell: (r) => <JobCell jc={r.job_card} client={r.client_name} demo={r.is_demo} /> },
    { key: 'revenue', header: 'Revenue', align: 'right', cell: (r) => formatINRShort(r.revenue) },
    {
      key: 'profit',
      header: 'Profit',
      align: 'right',
      cell: (r) => <span className={cn(r.profit < 0 && 'text-danger-foreground')}>{formatINRShort(r.profit)}</span>,
    },
    {
      key: 'margin_pct',
      header: 'Margin',
      align: 'right',
      cell: (r) => (
        <StatusChip size="sm" tone={r.margin_pct < 0 ? 'danger' : r.margin_pct < 0.1 ? 'warn' : 'neutral'}>
          {formatPercent(r.margin_pct)}
        </StatusChip>
      ),
    },
  ]

  const riskCols: Column<ProfitRiskRow>[] = [
    { key: 'job_card', header: 'Job', cell: (r) => <JobCell jc={r.job_card} client={r.client_name} demo={r.is_demo} /> },
    { key: 'po_value', header: 'PO value', align: 'right', cell: (r) => formatINRShort(r.po_value) },
    {
      key: 'wastage',
      header: 'Wastage',
      align: 'right',
      sortValue: (r) => r.wastage?.pct ?? null,
      cell: (r) => (r.wastage ? formatPercent(r.wastage.pct) : '—'),
    },
    {
      key: 'flags',
      header: 'Profit risk',
      sortable: false,
      cell: (r) =>
        r.flags.length ? (
          <div className="flex flex-wrap gap-1">
            {r.flags.map((f) => (
              <Badge key={f} size="sm" tone={f === 'client_locked' || f === 'wastage_high' ? 'danger' : 'warn'}>
                {FLAG_LABEL[f] ?? f}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-sm text-subtle-foreground">None flagged</span>
        ),
    },
  ]

  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Lowest-profit jobs"
        description={fromApi ? 'Invoiced jobs with the lowest profit in the period' : 'Jobs most at risk on profit (flags, wastage)'}
      />
      <div className="p-5 pt-4">
        {fromApi ? (
          <DataTable
            dense
            columns={profitCols}
            rows={fromApi}
            loading={loading}
            rowKey={(r) => r.job_card}
            onRowClick={(r) => navigate(`/jobs/${r.job_card}`)}
            empty={<EmptyState compact title="No invoiced jobs" description="No invoices were raised in this period." />}
          />
        ) : (
          <DataTable
            dense
            columns={riskCols}
            rows={riskRows}
            loading={loading}
            rowKey={(r) => r.job_card}
            onRowClick={(r) => navigate(`/jobs/${r.job_card}`)}
            empty={<EmptyState compact title="No jobs yet" description="Jobs appear here once POs are booked." />}
          />
        )}
      </div>
    </Card>
  )
}

/* Machines ---------------------------------------------------------- */

const MACHINE_PERIOD: Record<DashboardSummary['period'], string> = {
  today: 'Today',
  month: 'This month',
  year: 'This year',
}

function oeeTone(v: number): Tone {
  return v >= 0.65 ? 'ok' : v >= 0.5 ? 'warn' : 'danger'
}

export function MachinesCard({
  rows,
  loading,
  error,
  wastageTol,
  period,
}: {
  rows: MachineRow[] | undefined
  loading: boolean
  error?: UseApiResult<unknown> | null
  wastageTol: number
  /** Live: the figures are for the dashboard's period. null: this month (mock fixtures). */
  period?: DashboardSummary['period'] | null
}) {
  const navigate = useNavigate()
  const cols: Column<MachineRow>[] = [
    {
      key: 'name',
      header: 'Machine',
      cell: (r) => (
        <div className="flex items-center gap-2">
          <span className="font-medium text-foreground">{r.name}</span>
          <span className="text-sm text-subtle-foreground tabular">{r.id}</span>
          <DemoBadge show={r.is_demo} />
        </div>
      ),
    },
    {
      key: 'type',
      header: 'Type',
      cell: (r) => <Badge size="sm">{r.type === 'press' ? 'Press' : 'Offline'}</Badge>,
    },
    {
      key: 'oee',
      header: 'OEE',
      align: 'right',
      cell: (r) =>
        r.oee == null ? (
          <span className="text-subtle-foreground">—</span>
        ) : (
          <StatusChip size="sm" tone={oeeTone(r.oee)}>
            {formatPercent(r.oee)}
          </StatusChip>
        ),
    },
    {
      key: 'wastage',
      header: 'Wastage',
      align: 'right',
      cell: (r) =>
        r.wastage == null ? (
          <span className="text-subtle-foreground">—</span>
        ) : (
          <span className={cn(r.wastage > wastageTol && 'font-medium text-danger-foreground')}>
            {formatPercent(r.wastage)}
          </span>
        ),
    },
    { key: 'hours', header: 'Hours run', align: 'right', cell: (r) => formatNumber(r.hours, 1) },
    { key: 'hour_rate', header: 'Hour rate', align: 'right', cell: (r) => formatINRWhole(r.hour_rate) },
    {
      key: 'top_loss',
      header: 'Top loss',
      sortable: false,
      className: 'min-w-48',
      cell: (r) => <span className="text-sm text-muted-foreground">{r.top_loss ?? '—'}</span>,
    },
  ]
  return (
    <Card>
      <CardHeader
        title="Machines"
        description={`${period ? MACHINE_PERIOD[period] : 'This month'} · OEE = availability × performance × quality; wastage from ended press runs`}
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link to="/production">
              Production
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        }
      />
      <div className="p-5 pt-4">
        {error ? (
          <SectionError query={error} what="machines" />
        ) : (
          <DataTable
            dense
            columns={cols}
            rows={rows}
            loading={loading}
            rowKey={(r) => r.id}
            onRowClick={() => navigate('/production')}
            empty={<EmptyState compact title="No machines yet" description="Machines appear once masters are imported." />}
          />
        )}
      </div>
    </Card>
  )
}
