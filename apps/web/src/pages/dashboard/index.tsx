import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Banknote, Percent, Recycle, TrendingUp, Wallet } from 'lucide-react'
import type {
  AgentBrief,
  AlertsResponse,
  DashboardSummary,
  JobListResponse,
  Machine,
  Oee,
  Run,
  Settings,
} from '@contract/types'
import { Button, EmptyState, KpiCard, PageHeader, Segmented, Sparkline } from '@/components/ui'
import { API_MODE, useApi, withQuery } from '@/lib/api'
import { formatDate, formatINRShort, formatPercent } from '@/lib/format'
import { useMockSettings } from '../settings/store'
import {
  FIXTURE_WASTAGE_TOL,
  applyMockWastageTolerance,
  machineRows,
  profitRiskRows,
  sortAlerts,
  trendDelta,
  type SummaryExt,
} from './derive'
import { AlertsCard, BriefCard, LowProfitCard, MachinesCard, TopClientsCard, TrendCard } from './sections'

type Period = DashboardSummary['period']

const PERIODS: { value: Period; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
]

const DELTA_LABEL: Record<Period, string> = {
  today: 'vs 6-day avg',
  month: 'vs earlier weeks',
  year: 'vs earlier months',
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [period, setPeriod] = useState<Period>('month')

  const summaryQ = useApi<SummaryExt>(withQuery('/api/dashboard/summary', { period }))
  const briefQ = useApi<AgentBrief>('/api/agents/brief')
  const alertsQ = useApi<AlertsResponse>('/api/alerts')
  const settingsQ = useApi<Settings>('/api/settings')
  const jobsQ = useApi<JobListResponse>('/api/jobs')
  const runsQ = useApi<Run[]>('/api/production/runs')
  const machinesQ = useApi<Machine[]>('/api/machines')
  const oeeQ = useApi<Oee>('/api/production/oee')

  // Mock mode: settings saved on the Settings page live in a module store (see settings/store.ts).
  const mockSettings = useMockSettings()
  const wastageTol =
    (API_MODE === 'mock' ? mockSettings?.wastage_tol : undefined) ?? settingsQ.data?.wastage_tol ?? FIXTURE_WASTAGE_TOL

  const summary = summaryQ.data
  const jobs = jobsQ.data?.items
  const runs = runsQ.data

  const alerts = useMemo(() => {
    const base = alertsQ.data?.alerts
    if (!base) return undefined
    // MOCK ONLY: re-derive wastage alerts for a changed tolerance (live: backend recalculates).
    const shaped = API_MODE === 'mock' && jobs && runs ? applyMockWastageTolerance(base, wastageTol, jobs, runs) : base
    return sortAlerts(shaped)
  }, [alertsQ.data, jobs, runs, wastageTol])

  const toleranceNote =
    API_MODE === 'mock' && Math.abs(wastageTol - FIXTURE_WASTAGE_TOL) > 1e-9
      ? `Wastage limit is ${formatPercent(wastageTol, { digits: 0 })} (was ${formatPercent(FIXTURE_WASTAGE_TOL, {
          digits: 0,
        })}). Wastage alerts recalculated.`
      : null

  const riskRows = useMemo(() => (jobs && runs ? profitRiskRows(jobs, runs) : undefined), [jobs, runs])
  const machines = useMemo(
    () => (machinesQ.data ? machineRows(machinesQ.data, oeeQ.data, runs ?? []) : undefined),
    [machinesQ.data, oeeQ.data, runs],
  )

  const revenueSeries = summary?.trend.map((t) => t.revenue) ?? []
  const profitSeries = summary?.trend.map((t) => t.profit) ?? []
  const kpiLoading = summaryQ.loading && !summary
  const summaryFailed = summaryQ.error && !summaryQ.noData

  const subtitle = summary
    ? summary.from === summary.to
      ? formatDate(summary.from)
      : `${formatDate(summary.from)} – ${formatDate(summary.to)}`
    : 'Today, this month and this year at a glance.'

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle={subtitle}
        actions={<Segmented aria-label="Period" value={period} onChange={setPeriod} options={PERIODS} />}
      />

      <BriefCard query={briefQ} />

      {summaryFailed ? (
        <EmptyState
          icon={AlertTriangle}
          title="Couldn't load the summary"
          description={summaryQ.error?.message}
          action={
            <Button variant="secondary" size="sm" onClick={summaryQ.refetch}>
              Try again
            </Button>
          }
        />
      ) : summaryQ.noData ? (
        <EmptyState title="No numbers yet" description="Sales and profit appear once the first invoices are raised." />
      ) : (
        <section aria-label="Key figures" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <KpiCard
            label="Sales (dispatch value)"
            icon={TrendingUp}
            loading={kpiLoading}
            value={summary?.revenue ?? 0}
            delta={trendDelta(revenueSeries)}
            deltaLabel={DELTA_LABEL[period]}
            sparkline={<Sparkline data={revenueSeries} color="var(--chart-1)" />}
            footer={summary && `${summary.invoices_count} invoices · booked ${formatINRShort(summary.orders_booked_value)}`}
          />
          <KpiCard
            label="Gross profit"
            icon={Percent}
            loading={kpiLoading}
            value={summary?.gross_profit ?? 0}
            delta={trendDelta(profitSeries)}
            deltaLabel={DELTA_LABEL[period]}
            sparkline={<Sparkline data={profitSeries} color="var(--chart-2)" />}
            footer={summary && `Margin ${formatPercent(summary.margin_pct)}`}
          />
          <KpiCard
            label="Cash receivable"
            icon={Wallet}
            loading={kpiLoading}
            value={summary?.receivables ?? 0}
            onClick={() => navigate('/money?tab=debtors')}
            footer={
              summary && (
                <span>
                  Overdue <span className="text-danger-foreground">{formatINRShort(summary.overdue)}</span>
                  {summary.locked_clients > 0 && ` · ${summary.locked_clients} locked`}
                </span>
              )
            }
          />
          <KpiCard
            label="Payable in 7 days"
            icon={Banknote}
            loading={kpiLoading}
            value={summary?.payables_due_7d ?? 0}
            onClick={() => navigate('/money?tab=creditors')}
            footer={summary && `In ${formatINRShort(summary.cash_in)} · out ${formatINRShort(summary.cash_out)}`}
          />
          <KpiCard
            label="Wastage"
            icon={Recycle}
            loading={kpiLoading}
            value={
              summary ? (
                <span className={summary.wastage_pct > wastageTol ? 'text-danger-foreground' : undefined}>
                  {formatPercent(summary.wastage_pct)}
                </span>
              ) : (
                '—'
              )
            }
            onClick={() => navigate('/production')}
            footer={summary && `Limit ${formatPercent(wastageTol, { digits: 0 })} · OEE ${formatPercent(summary.oee)}`}
          />
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <TrendCard summary={summary} loading={summaryQ.loading} />
        </div>
        <div className="xl:col-span-2">
          <AlertsCard query={alertsQ} alerts={alerts} asOf={alertsQ.data?.as_of} note={toleranceNote} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <TopClientsCard summary={summary} loading={summaryQ.loading} />
        <LowProfitCard summary={summary} riskRows={riskRows} loading={jobsQ.loading || runsQ.loading} />
      </div>

      <MachinesCard
        rows={machines}
        loading={machinesQ.loading}
        error={machinesQ.error && !machinesQ.noData ? machinesQ : null}
        wastageTol={wastageTol}
      />
    </div>
  )
}
