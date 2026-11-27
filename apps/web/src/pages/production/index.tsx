import { useMemo, useState } from 'react'
import { Factory } from 'lucide-react'
import type { JobListResponse, Machine, Run, Settings } from '@contract/types'
import { api, useApi } from '@/lib/api'
import { withAdded } from '@/pages/store/common'
import { formatDateTime, formatNumber, formatPercent } from '@/lib/format'
import {
  type Column,
  DataTable,
  DemoBadge,
  EmptyState,
  PageHeader,
  QueryState,
  SectionHeader,
  Skeleton,
  StatusChip,
} from '@/components/ui'
import { EndRunDialog, LiveMeter, PressCard, RunResultCard, StartRunDialog } from './presses'
import { DowntimeCard, MorningReportCard, OeeSection, PressSetupCard } from './insights'
import { useLiveCounter } from './useLiveCounter'

export default function ProductionPage() {
  const machinesQ = useApi<Machine[]>('/api/machines')
  const runsQ = useApi<Run[]>('/api/production/runs')
  const jobsQ = useApi<JobListResponse>('/api/jobs')
  const settingsQ = useApi<Settings>('/api/settings')
  const tol = settingsQ.data?.wastage_tol ?? 0.15

  const [overrides, setOverrides] = useState<Record<string, Run>>({})
  const [extra, setExtra] = useState<Run[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [startFor, setStartFor] = useState<Machine | null>(null)
  const [endRun, setEndRun] = useState<Run | null>(null)
  const [result, setResult] = useState<Run | null>(null)

  const runs = useMemo(
    () => withAdded(extra, (runsQ.data ?? []).map((r) => overrides[r.id] ?? r)),
    [extra, runsQ.data, overrides],
  )
  // Live mode: reload runs and jobs after a start/end (job status, printed totals, morning numbers).
  const refreshLive = () => {
    if (api.mode !== 'live') return
    runsQ.refetch()
    jobsQ.refetch()
  }
  const presses = useMemo(() => (machinesQ.data ?? []).filter((m) => m.type === 'press'), [machinesQ.data])
  const jobs = jobsQ.data?.items ?? []

  const runningOn = (machineId: string) => runs.find((r) => r.machine_id === machineId && r.status === 'running') ?? null
  const selectedMachineId = selectedId ?? presses.find((m) => runningOn(m.id))?.id ?? null
  const selectedRun = selectedMachineId ? runningOn(selectedMachineId) : null
  const selectedJob = jobs.find((j) => j.job_card === selectedRun?.job_card)
  const live = useLiveCounter(selectedRun, selectedJob?.ups ?? 0, selectedJob?.repeat_mm ?? 0)

  const columns: Column<Run>[] = [
    {
      key: 'id',
      header: 'Run',
      cell: (r) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {r.id} <DemoBadge show={r.is_demo} />
        </span>
      ),
    },
    { key: 'machine_name', header: 'Machine' },
    { key: 'job_card', header: 'Job', cell: (r) => `${r.job_card} · ${r.client_name}` },
    { key: 'start', header: 'Start', cell: (r) => formatDateTime(r.start) },
    { key: 'printed_qty', header: 'Printed', align: 'right', cell: (r) => formatNumber(r.printed_qty) },
    {
      key: 'wastage_pct',
      header: 'Wastage',
      align: 'right',
      cell: (r) =>
        r.wastage_pct === null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <StatusChip size="sm" tone={r.wastage_flag || r.wastage_pct > tol ? 'danger' : 'ok'}>
            {formatPercent(r.wastage_pct)}
          </StatusChip>
        ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => (
        <StatusChip size="sm" tone={r.status === 'running' ? 'ok' : 'neutral'}>
          {r.status === 'running' ? 'Running' : 'Ended'}
        </StatusChip>
      ),
    },
  ]

  return (
    <div className="space-y-8">
      <PageHeader title="Production" subtitle="Presses, live meter counts, wastage, OEE and the morning report. Built for the shop-floor tablet." />

      <section aria-label="Presses" className="space-y-4">
        <QueryState
          query={machinesQ}
          loading={
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-60 rounded-lg" />
              ))}
            </div>
          }
          isEmpty={() => presses.length === 0}
          empty={<EmptyState icon={Factory} title="No presses set up" />}
        >
          {() => (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {presses.map((m) => {
                const run = runningOn(m.id)
                return (
                  <PressCard
                    key={m.id}
                    machine={m}
                    run={run}
                    selected={m.id === selectedMachineId}
                    liveCount={run && run.id === selectedRun?.id ? (live.tick?.count ?? null) : null}
                    onSelect={() => setSelectedId(m.id)}
                    onStart={() => setStartFor(m)}
                    onEnd={() => run && setEndRun(run)}
                  />
                )
              })}
            </div>
          )}
        </QueryState>

        {result && <RunResultCard run={result} tol={tol} onDismiss={() => setResult(null)} />}

        {selectedRun ? (
          <LiveMeter run={selectedRun} job={selectedJob} live={live} tol={tol} onEnd={() => setEndRun(selectedRun)} />
        ) : (
          selectedMachineId && (
            <EmptyState compact icon={Factory} title="This press is idle" description="Start a run to see the live meter." />
          )
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <PressSetupCard jobCard={selectedRun?.job_card ?? null} />
        <DowntimeCard runs={runs} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <OeeSection />
        <MorningReportCard tol={tol} />
      </div>

      <section>
        <SectionHeader title="Runs this month" description="Printed totals count press runs only." />
        <QueryState query={runsQ}>
          {() => <DataTable rows={runs} columns={columns} defaultSort={{ key: 'start', dir: 'desc' }} />}
        </QueryState>
      </section>

      <StartRunDialog
        machine={startFor}
        jobs={jobs}
        onClose={() => setStartFor(null)}
        onStarted={(r) => {
          setExtra((x) => [r, ...x])
          setSelectedId(r.machine_id)
          setStartFor(null)
          refreshLive()
        }}
      />
      <EndRunDialog
        run={endRun}
        job={jobs.find((j) => j.job_card === endRun?.job_card)}
        initialCount={endRun && endRun.id === selectedRun?.id ? (live.tick?.count ?? null) : null}
        initialMetres={endRun && endRun.id === selectedRun?.id ? (live.tick?.metres ?? null) : null}
        settings={settingsQ.data}
        onClose={() => setEndRun(null)}
        onEnded={(r) => {
          if (extra.some((x) => x.id === r.id)) setExtra((x) => x.map((e) => (e.id === r.id ? r : e)))
          else setOverrides((o) => ({ ...o, [r.id]: r }))
          setResult(r)
          setEndRun(null)
          refreshLive()
        }}
      />
    </div>
  )
}
