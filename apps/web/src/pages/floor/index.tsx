import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Factory, Gauge, Moon, RefreshCw, Sun, Timer, User } from 'lucide-react'
import type { FloorBoard, FloorMachine, Job, JobListResponse, MorningReport, Oee, Run, Settings } from '@contract/types'
import { DemoBadge, Skeleton } from '@/components/ui'
import { api, useApi, useSampleDataShown } from '@/lib/api'
import { formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

type Tone = 'ok' | 'warn' | 'danger' | 'neutral'

const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-ok-foreground',
  warn: 'text-warn-foreground',
  danger: 'text-danger-foreground',
  neutral: 'text-muted-foreground',
}
const TONE_BAR: Record<Tone, string> = { ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger', neutral: 'bg-subtle-foreground' }
const TONE_STROKE: Record<Tone, string> = { ok: 'var(--ok)', warn: 'var(--warn)', danger: 'var(--danger)', neutral: 'var(--subtle-foreground)' }

const STATUS: Record<FloorMachine['status'], { label: string; tone: Tone }> = {
  running: { label: 'Running', tone: 'ok' },
  setup: { label: 'Setup', tone: 'warn' },
  stopped: { label: 'Stopped', tone: 'danger' },
  idle: { label: 'Idle', tone: 'neutral' },
}

const QUEUE_STATUSES: Job['status'][] = ['planned', 'design', 'printing', 'hold']
const PRIORITY = { high: 0, normal: 1, low: 2 }

function timeHM(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/* ------------------------------------------------------------------ */

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(t)
  }, [])
  return (
    <div className="text-right leading-tight">
      <div className="tabular text-[clamp(1.75rem,2.6vw,3rem)] font-semibold tracking-tight">
        {now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
      </div>
      <div className="text-[clamp(0.875rem,1vw,1.125rem)] text-muted-foreground">
        {now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}
      </div>
    </div>
  )
}

/** Seconds since the board data arrived; drives the simulated counter in mock mode. */
function useElapsed(active: boolean, resetKey: unknown): number {
  const [elapsed, setElapsed] = useState(0)
  const start = useRef(Date.now())
  useEffect(() => {
    start.current = Date.now()
    setElapsed(0)
  }, [resetKey])
  useEffect(() => {
    if (!active) return
    const t = window.setInterval(() => setElapsed((Date.now() - start.current) / 1000), 1000)
    return () => window.clearInterval(t)
  }, [active])
  return elapsed
}

function OeeRing({ value }: { value: number | null }) {
  const r = 34
  const c = 2 * Math.PI * r
  const v = value ?? 0
  const tone: Tone = value == null ? 'neutral' : v >= 0.6 ? 'ok' : v >= 0.45 ? 'warn' : 'danger'
  return (
    <div className="relative size-[clamp(4.5rem,6vw,7rem)] shrink-0">
      <svg viewBox="0 0 80 80" className="size-full -rotate-90" role="img" aria-label={`OEE ${formatPercent(value, { digits: 0 })}`}>
        <circle cx="40" cy="40" r={r} fill="none" stroke="var(--border)" strokeWidth="7" />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke={TONE_STROKE[tone]}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${c * Math.min(1, v)} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="tabular text-[clamp(1rem,1.4vw,1.625rem)] font-semibold">{formatPercent(value, { digits: 0 })}</span>
      </div>
    </div>
  )
}

interface PressExtras {
  oee: number | null
  wastageYesterday: number | null
  ranYesterday: boolean
  queue: { job_card: string; client: string; product: string }[]
  runsToday: number
}

function PressColumn({
  m,
  extras,
  elapsed,
  simulate,
  tol,
}: {
  m: FloorMachine
  extras: PressExtras
  elapsed: number
  simulate: boolean
  tol: number
}) {
  const st = STATUS[m.status]
  const running = m.status === 'running'
  const addM = simulate && running ? (m.speed_mpm * elapsed) / 60 : 0
  const perMetre = m.metres_run > 0 ? m.counter / m.metres_run : 0
  const counter = Math.min(m.target || Infinity, Math.round(m.counter + addM * perMetre))
  const metres = m.metres_run + addM
  const progress = m.target > 0 ? Math.min(1, counter / m.target) : m.progress_pct
  const w = extras.wastageYesterday
  const wTone: Tone = !extras.ranYesterday || w == null ? 'neutral' : w > tol ? 'danger' : w > tol * 0.8 ? 'warn' : 'ok'

  return (
    <section
      aria-label={m.machine_name}
      className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-surface"
    >
      <div className={cn('h-1.5', TONE_BAR[st.tone])} aria-hidden />
      <div className="flex flex-1 flex-col gap-[clamp(0.75rem,1.4vh,1.5rem)] p-[clamp(1rem,1.3vw,1.75rem)]">
        {/* Name + status */}
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-[clamp(1.25rem,1.7vw,2.125rem)] leading-tight font-semibold">{m.machine_name}</h2>
          <span
            className={cn(
              'inline-flex shrink-0 items-center gap-2 rounded-full border border-current/25 px-3 py-1 text-[clamp(0.875rem,1vw,1.25rem)] font-semibold',
              TONE_TEXT[st.tone],
            )}
          >
            <span className={cn('size-2.5 rounded-full', TONE_BAR[st.tone], running && 'animate-pulse')} aria-hidden />
            {st.label}
          </span>
        </div>

        {/* Now running */}
        <div className="min-w-0">
          <div className="text-[clamp(0.75rem,0.8vw,1rem)] font-medium tracking-wide text-muted-foreground uppercase">Now</div>
          {m.job_card ? (
            <>
              <div className="tabular text-[clamp(1.75rem,2.6vw,3.25rem)] leading-tight font-bold tracking-tight">{m.job_card}</div>
              <div className="truncate text-[clamp(1rem,1.25vw,1.5rem)] font-medium">{m.client_name}</div>
              <div className="truncate text-[clamp(0.875rem,0.95vw,1.125rem)] text-muted-foreground">{m.product}</div>
            </>
          ) : (
            <div className="text-[clamp(1.25rem,1.6vw,2rem)] text-muted-foreground">No job on press</div>
          )}
          {m.status === 'stopped' && m.stop_reason && (
            <div className="mt-2 rounded-md bg-danger-soft px-3 py-1.5 text-[clamp(0.9rem,1vw,1.25rem)] font-semibold text-danger-foreground">
              {m.stop_reason}
            </div>
          )}
        </div>

        {/* Live counter */}
        <div className="rounded-lg bg-surface-muted p-[clamp(0.75rem,1vw,1.25rem)]">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[clamp(0.75rem,0.8vw,1rem)] font-medium tracking-wide text-muted-foreground uppercase">
              Metres run
            </span>
            <span className="tabular text-[clamp(0.875rem,0.95vw,1.125rem)] text-muted-foreground">
              {formatNumber(running ? m.speed_mpm : 0)} m/min
            </span>
          </div>
          <div className="tabular text-[clamp(2.25rem,3.6vw,4.5rem)] leading-none font-bold tracking-tight" aria-live="off">
            {formatNumber(metres, 0)}
            <span className="ml-1 text-[0.45em] font-semibold text-muted-foreground">m</span>
          </div>
          <div className="mt-3 h-3 overflow-hidden rounded-full bg-border">
            <div className={cn('h-full rounded-full', TONE_BAR[st.tone === 'neutral' ? 'neutral' : 'ok'])} style={{ width: `${progress * 100}%` }} />
          </div>
          <div className="tabular mt-1.5 flex justify-between gap-2 text-[clamp(0.875rem,0.95vw,1.125rem)]">
            <span>
              <strong>{formatNumber(counter)}</strong>
              <span className="text-muted-foreground"> / {formatNumber(m.target)} labels</span>
            </span>
            <span className="text-muted-foreground">ETA {timeHM(m.eta)}</span>
          </div>
        </div>

        {/* OEE + wastage */}
        <div className="flex items-center gap-4">
          <OeeRing value={extras.oee} />
          <div className="grid min-w-0 flex-1 grid-cols-1 gap-2">
            <div>
              <div className="text-[clamp(0.75rem,0.8vw,1rem)] text-muted-foreground">OEE this month</div>
            </div>
            <div>
              <div className="text-[clamp(0.75rem,0.8vw,1rem)] text-muted-foreground">Wastage yesterday</div>
              <div className={cn('tabular text-[clamp(1.25rem,1.7vw,2.125rem)] leading-tight font-bold', TONE_TEXT[wTone])}>
                {extras.ranYesterday && w != null ? formatPercent(w) : 'No runs'}
              </div>
              <div className="text-[clamp(0.7rem,0.75vw,0.9rem)] text-muted-foreground">Limit {formatPercent(tol, { digits: 0 })}</div>
            </div>
          </div>
        </div>

        {/* Queue */}
        <div className="min-w-0">
          <div className="mb-1.5 text-[clamp(0.75rem,0.8vw,1rem)] font-medium tracking-wide text-muted-foreground uppercase">Next up</div>
          {extras.queue.length === 0 ? (
            <div className="text-[clamp(0.875rem,1vw,1.25rem)] text-muted-foreground">Queue empty</div>
          ) : (
            <ol className="space-y-1.5">
              {extras.queue.map((q, i) => (
                <li key={q.job_card} className="flex min-w-0 items-baseline gap-3 text-[clamp(0.9rem,1.05vw,1.3rem)]">
                  <span className="tabular w-5 shrink-0 text-muted-foreground">{i + 1}</span>
                  <span className="tabular shrink-0 font-semibold">{q.job_card}</span>
                  <span className="truncate text-muted-foreground">{q.client}</span>
                </li>
              ))}
            </ol>
          )}
        </div>

        {/* Footer */}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border pt-3 text-[clamp(0.875rem,0.95vw,1.125rem)] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <User className="size-4" aria-hidden />
            {m.operator ?? '—'}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Timer className="size-4" aria-hidden />
            Runs today <strong className="tabular text-foreground">{extras.runsToday}</strong>
          </span>
        </div>
        {m.alert && (
          <div className="flex items-center gap-2 rounded-md bg-warn-soft px-3 py-2 text-[clamp(0.875rem,1vw,1.25rem)] font-medium text-warn-foreground">
            <AlertTriangle className="size-5 shrink-0" aria-hidden />
            <span className="truncate">{m.alert}</span>
          </div>
        )}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

export default function FloorBoardPage() {
  const [dark, setDark] = useState(true)
  const board = useApi<FloorBoard>('/api/floor/board')
  const oee = useApi<Oee>('/api/production/oee')
  const morning = useApi<MorningReport>('/api/production/morning-report')
  const jobs = useApi<JobListResponse>('/api/jobs')
  const runs = useApi<Run[]>('/api/production/runs')
  const settings = useApi<Settings>('/api/settings')

  const simulate = api.mode === 'mock'
  const { refetch } = board
  // Live mode: refresh the board every 15 s (mock mode ticks locally instead).
  useEffect(() => {
    if (simulate) return
    const t = window.setInterval(refetch, 15_000)
    return () => window.clearInterval(t)
  }, [simulate, refetch])

  const elapsed = useElapsed(simulate && !!board.data, board.data)
  const tol = settings.data?.wastage_tol ?? 0.15

  const extras = useMemo(() => {
    const out: Record<string, PressExtras> = {}
    const data = board.data
    if (!data) return out
    const today = data.as_of.slice(0, 10)
    const jobList = jobs.data?.items ?? []
    for (const m of data.machines) {
      const om = oee.data?.machines.find((x) => x.machine_id === m.machine_id)
      const mm = morning.data?.machines.find((x) => x.machine_id === m.machine_id)
      const candidates = jobList
        .filter((j) => j.machine_id === m.machine_id && j.job_card !== m.job_card && QUEUE_STATUSES.includes(j.status))
        .sort(
          (a, b) =>
            (a.job_card === m.next_job_card ? -1 : 0) - (b.job_card === m.next_job_card ? -1 : 0) ||
            PRIORITY[a.priority] - PRIORITY[b.priority] ||
            a.due_date.localeCompare(b.due_date),
        )
        .map((j) => ({ job_card: j.job_card, client: j.client_name, product: j.product }))
      if (m.next_job_card && !candidates.some((c) => c.job_card === m.next_job_card)) {
        candidates.unshift({ job_card: m.next_job_card, client: '', product: '' })
      }
      out[m.machine_id] = {
        oee: om?.oee ?? null,
        wastageYesterday: mm?.wastage_pct ?? null,
        ranYesterday: (mm?.runs ?? 0) > 0,
        queue: candidates.slice(0, 3),
        runsToday: (runs.data ?? []).filter((r) => r.machine_id === m.machine_id && r.start.slice(0, 10) === today).length,
      }
    }
    return out
  }, [board.data, oee.data, morning.data, jobs.data, runs.data])

  const ticker = useMemo(() => {
    const d = board.data
    if (!d) return []
    const machineAlerts = d.machines.filter((m) => m.alert).map((m) => `${m.machine_name}: ${m.alert}`)
    return [...machineAlerts, ...d.ticker]
  }, [board.data])

  const plant = settings.data?.company_name ?? 'Pro Labels'
  const sampleShown = useSampleDataShown()

  return (
    <div className={cn(dark && 'dark', 'flex min-h-screen flex-col bg-background text-foreground')}>
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border px-[clamp(1rem,2vw,2.5rem)] py-[clamp(0.75rem,1.5vh,1.5rem)]">
        <div className="flex min-w-0 items-center gap-4">
          <span className="flex size-[clamp(2.5rem,3vw,3.5rem)] shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-soft-foreground">
            <Factory className="size-1/2" aria-hidden />
          </span>
          <div className="min-w-0">
            <div className="truncate text-[clamp(0.875rem,1vw,1.25rem)] text-muted-foreground">{plant}</div>
            <div className="flex items-center gap-3">
              <h1 className="text-[clamp(1.5rem,2.2vw,2.75rem)] leading-tight font-semibold tracking-tight">Floor Board</h1>
              <DemoBadge
                show={sampleShown}
                label="Sample data"
                title="The live backend does not serve the floor board yet; showing sample data from the demo fixtures."
              />
            </div>
          </div>
        </div>

        {board.data && (
          <div className="tabular flex flex-wrap items-center gap-x-[clamp(1rem,2.5vw,3rem)] gap-y-1">
            <HeaderStat label="Shift" value={board.data.shift === 'day' ? 'Day' : 'Night'} />
            <HeaderStat label="Printed today" value={formatNumber(board.data.today.printed_qty)} />
            <HeaderStat label="Jobs done" value={formatNumber(board.data.today.jobs_done)} />
            <HeaderStat
              label="Wastage today"
              value={formatPercent(board.data.today.wastage_pct)}
              tone={board.data.today.wastage_pct > tol ? 'danger' : 'ok'}
            />
          </div>
        )}

        <div className="flex items-center gap-[clamp(0.75rem,1.5vw,2rem)]">
          <Clock />
          <div className="flex flex-col gap-1.5">
            <Link
              to="/"
              className="inline-flex h-10 items-center gap-2 rounded-md border border-border px-3 text-base font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
            >
              <ArrowLeft className="size-4" aria-hidden /> Exit board
            </Link>
            <button
              type="button"
              onClick={() => setDark((d) => !d)}
              className="inline-flex h-8 items-center justify-center gap-2 rounded-md px-3 text-sm text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
              aria-label={dark ? 'Switch to light' : 'Switch to dark'}
            >
              {dark ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
              {dark ? 'Light' : 'Dark'}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 p-[clamp(0.75rem,1.4vw,2rem)]">
        {board.data ? (
          board.data.machines.length === 0 ? (
            <BoardMessage icon={Gauge} title="No presses set up" text="Add machines in Settings to see them here." />
          ) : (
            <div className="grid h-full grid-cols-1 gap-[clamp(0.75rem,1.2vw,1.75rem)] md:grid-cols-2 xl:grid-cols-4">
              {board.data.machines.map((m) => (
                <PressColumn
                  key={m.machine_id}
                  m={m}
                  extras={extras[m.machine_id] ?? { oee: null, wastageYesterday: null, ranYesterday: false, queue: [], runsToday: 0 }}
                  elapsed={elapsed}
                  simulate={simulate}
                  tol={tol}
                />
              ))}
            </div>
          )
        ) : board.loading ? (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4" role="status" aria-label="Loading board">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[70vh] rounded-xl" />
            ))}
          </div>
        ) : board.noData ? (
          <BoardMessage icon={Gauge} title="No live data yet" text="The board fills in when a press run starts." />
        ) : (
          <BoardMessage
            icon={AlertTriangle}
            title="Board is offline"
            text={board.error?.message ?? 'Could not load the floor board.'}
            action={
              <button
                type="button"
                onClick={board.refetch}
                className="inline-flex h-11 items-center gap-2 rounded-md bg-accent px-5 text-md font-medium text-accent-foreground hover:bg-accent-hover"
              >
                <RefreshCw className="size-4" aria-hidden /> Try again
              </button>
            }
          />
        )}
      </main>

      {ticker.length > 0 && (
        <footer className="border-t border-border bg-surface px-[clamp(1rem,2vw,2.5rem)] py-[clamp(0.6rem,1.2vh,1.1rem)]" aria-label="Alerts">
          <ul className="flex flex-wrap items-center gap-x-8 gap-y-1 text-[clamp(0.95rem,1.15vw,1.5rem)] font-medium">
            {ticker.map((t, i) => (
              <li key={i} className="flex min-w-0 items-center gap-2.5">
                <span className={cn('size-2.5 shrink-0 rounded-full', i < ticker.length - (board.data?.ticker.length ?? 0) ? 'bg-warn' : 'bg-accent')} aria-hidden />
                <span className="truncate">{t}</span>
              </li>
            ))}
          </ul>
        </footer>
      )}
    </div>
  )
}

function HeaderStat({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="leading-tight">
      <div className="text-[clamp(0.75rem,0.85vw,1rem)] text-muted-foreground">{label}</div>
      <div className={cn('text-[clamp(1.125rem,1.6vw,2rem)] font-semibold', tone && TONE_TEXT[tone])}>{value}</div>
    </div>
  )
}

function BoardMessage({
  icon: Icon,
  title,
  text,
  action,
}: {
  icon: typeof Gauge
  title: string
  text: string
  action?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
      <span className="flex size-16 items-center justify-center rounded-xl border border-border bg-surface-muted">
        <Icon className="size-8 text-muted-foreground" aria-hidden />
      </span>
      <p className="text-2xl font-semibold">{title}</p>
      <p className="max-w-md text-md text-muted-foreground">{text}</p>
      {action}
    </div>
  )
}
