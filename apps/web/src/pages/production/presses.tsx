import { useState } from 'react'
import { CirclePause, CirclePlay, Factory, Gauge, Pause, Play, Square, Timer, User } from 'lucide-react'
import type { Job, Machine, Run, RunEnd, RunStart, Settings } from '@contract/types'
import { api } from '@/lib/api'
import { formatDateTime, formatINR, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  DemoBadge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  Select,
  StatusChip,
  toast,
} from '@/components/ui'
import { describeError, InlineAlert } from '@/pages/store/common'
import type { LiveCounter } from './useLiveCounter'
import { appNowIso } from '@/lib/clock'

export const DOWNTIME_REASONS = [
  'Make-ready',
  'Plate damage',
  'Colour matching',
  'Ink top-up',
  'Web break',
  'Waiting for material',
  'Maintenance',
  'Power cut',
  'Other',
]

/* ------------------------------------------------------------------ */
/* Press card                                                          */
/* ------------------------------------------------------------------ */

export function PressCard({
  machine,
  run,
  selected,
  liveCount,
  onSelect,
  onStart,
  onEnd,
}: {
  machine: Machine
  run: Run | null
  selected: boolean
  liveCount: number | null
  onSelect: () => void
  onStart: () => void
  onEnd: () => void
}) {
  const running = run?.status === 'running'
  return (
    <Card
      interactive
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn('flex flex-col p-5', selected && 'border-accent ring-2 ring-accent/30')}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-md font-semibold text-foreground">{machine.name}</p>
          <p className="text-sm text-muted-foreground">
            {machine.units} units · {machine.web_width_mm} mm · {formatINR(machine.hour_rate)}/h
          </p>
        </div>
        <StatusChip tone={running ? 'ok' : 'neutral'}>{running ? 'Running' : 'Idle'}</StatusChip>
      </div>
      <div className="mt-4 min-h-[88px] flex-1 rounded-md bg-surface-muted p-3">
        {running && run ? (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-foreground">{run.job_card}</span>
              <DemoBadge show={run.is_demo} />
            </div>
            <p className="truncate text-sm text-muted-foreground">{run.client_name}</p>
            <div className="mt-2 flex items-center justify-between gap-2 text-sm">
              <span className="inline-flex items-center gap-1 text-muted-foreground">
                <User className="size-3.5" aria-hidden /> {run.operator} · {run.shift}
              </span>
              <span className="tabular font-semibold text-foreground">{formatNumber(liveCount ?? run.printed_qty)}</span>
            </div>
          </>
        ) : (
          <div className="flex h-full items-center gap-2 text-sm text-muted-foreground">
            <Factory className="size-4" aria-hidden /> No job on press
          </div>
        )}
      </div>
      <div className="mt-4" onClick={(e) => e.stopPropagation()}>
        {running ? (
          <Button size="touch" variant="secondary" className="w-full" onClick={onEnd}>
            <Square aria-hidden /> End run
          </Button>
        ) : (
          <Button size="touch" className="w-full" onClick={onStart}>
            <Play aria-hidden /> Start run
          </Button>
        )}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Live meter                                                          */
/* ------------------------------------------------------------------ */

export function LiveMeter({
  run,
  job,
  live,
  tol,
  onEnd,
}: {
  run: Run
  job: Job | undefined
  live: LiveCounter
  tol: number
  onEnd: () => void
}) {
  const t = live.tick
  const count = t?.count ?? run.printed_qty
  const used = t?.metres ?? 0
  const required = job && job.ups > 0 ? ((count / job.ups) * job.repeat_mm) / 1000 : run.required_m && job ? (run.required_m * count) / job.order_qty : 0
  const wastage = used - required
  const pct = required > 0 ? wastage / required : null
  const over = pct !== null && pct > tol
  const progress = job ? Math.min(1, count / job.order_qty) : null

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <span className="relative flex size-2.5">
              {t && !live.paused && <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok opacity-60" />}
              <span className={cn('relative inline-flex size-2.5 rounded-full', t && !live.paused ? 'bg-ok' : 'bg-subtle-foreground')} />
            </span>
            Live meter · {run.machine_name}
          </span>
        }
        description={`${run.id} · ${run.job_card} · ${run.client_name} · started ${formatDateTime(run.start)}`}
        actions={
          <>
            <Badge tone={live.source === 'sse' ? 'ok' : 'neutral'} size="sm">
              {live.source === 'sse' ? 'Live stream' : live.source === 'sim' ? 'Simulated (demo)' : 'Connecting…'}
            </Badge>
            <Button size="lg" variant="ghost" onClick={() => live.setPaused(!live.paused)} aria-label={live.paused ? 'Resume meter' : 'Pause meter'}>
              {live.paused ? <CirclePlay aria-hidden /> : <CirclePause aria-hidden />}
            </Button>
          </>
        }
      />
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MeterTile label="Printed (count)" value={formatNumber(count)} sub={job ? `of ${formatNumber(job.order_qty)} ordered` : undefined} big />
          <MeterTile label="Used" value={`${formatNumber(used, 1)} m`} sub={t ? `${formatNumber(t.speed_mpm, 1)} m/min` : '—'} big />
          <MeterTile label="Required for this count" value={`${formatNumber(required, 1)} m`} sub={job ? `${job.ups} ups · ${job.repeat_mm} mm repeat` : undefined} big />
          <div className={cn('rounded-lg border p-4', over ? 'border-danger/30 bg-danger-soft' : 'border-ok/20 bg-ok-soft')}>
            <p className={cn('text-xs font-medium', over ? 'text-danger-foreground' : 'text-ok-foreground')}>Wastage</p>
            <p className={cn('tabular mt-1 text-3xl font-semibold tracking-tight', over ? 'text-danger-foreground' : 'text-ok-foreground')}>
              {formatPercent(pct)}
            </p>
            <p className={cn('tabular text-sm', over ? 'text-danger-foreground' : 'text-ok-foreground')}>
              {formatNumber(wastage, 1)} m · limit {formatPercent(tol, { digits: 0 })}
            </p>
          </div>
        </div>
        {progress !== null && (
          <div>
            <div className="mb-1.5 flex justify-between text-sm text-muted-foreground">
              <span>Order progress</span>
              <span className="tabular">{formatPercent(progress)}</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-surface-sunken">
              <div className="h-full rounded-full bg-chart-1 transition-[width] duration-700 ease-out" style={{ width: `${progress * 100}%` }} />
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <Gauge className="size-4" aria-hidden /> Counter reads the press meter every second. Wastage = used − required.
          </p>
          <Button size="touch" variant="secondary" onClick={onEnd}>
            <Square aria-hidden /> End this run
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function MeterTile({ label, value, sub, big }: { label: string; value: string; sub?: string; big?: boolean }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={cn('tabular mt-1 font-semibold tracking-tight text-foreground', big ? 'text-3xl' : 'text-xl')}>{value}</p>
      {sub && <p className="text-sm text-muted-foreground">{sub}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Result card                                                         */
/* ------------------------------------------------------------------ */

export function RunResultCard({ run, tol, onDismiss }: { run: Run; tol: number; onDismiss?: () => void }) {
  const flag = run.wastage_flag || (run.wastage_pct ?? 0) > tol
  return (
    <Card className={cn(flag ? 'border-danger/30' : 'border-ok/30')}>
      <CardHeader
        title={`Run result · ${run.id}`}
        description={`${run.job_card} · ${run.client_name} · ${run.machine_name} · ${run.operator} (${run.shift})`}
        actions={
          <>
            <StatusChip tone={flag ? 'danger' : 'ok'}>
              {flag ? `Wastage above ${formatPercent(tol, { digits: 0 })}` : `Within ${formatPercent(tol, { digits: 0 })} tolerance`}
            </StatusChip>
            {run.overprod_flag && <StatusChip tone="warn">Over-production</StatusChip>}
            {onDismiss && (
              <Button variant="ghost" size="sm" onClick={onDismiss}>
                Dismiss
              </Button>
            )}
          </>
        }
      />
      <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-7">
        <ResultStat label="Used" value={`${formatNumber(run.used_m, 1)} m`} />
        <ResultStat label="Required" value={`${formatNumber(run.required_m, 1)} m`} />
        <ResultStat
          label="Wastage"
          value={formatPercent(run.wastage_pct)}
          sub={`${formatNumber(run.wastage_m, 1)} m`}
          tone={flag ? 'danger' : 'ok'}
        />
        <ResultStat label="Printed" value={formatNumber(run.printed_qty)} />
        <ResultStat label="Hours" value={formatNumber(run.hours, 2)} />
        <ResultStat label="Crew cost" value={formatINR(run.crew_cost)} sub={`${formatINR(run.hour_rate)}/h`} />
        <ResultStat
          label="Downtime"
          value={`${run.stops.reduce((a, s) => a + s.minutes, 0)} min`}
          sub={run.stops.map((s) => s.reason).join(', ') || 'none'}
        />
      </CardContent>
    </Card>
  )
}

function ResultStat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'ok' | 'danger' }) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p
        className={cn(
          'tabular mt-0.5 text-xl font-semibold',
          tone === 'danger' ? 'text-danger-foreground' : tone === 'ok' ? 'text-ok-foreground' : 'text-foreground',
        )}
      >
        {value}
      </p>
      {sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Start run                                                           */
/* ------------------------------------------------------------------ */

export function StartRunDialog({
  machine,
  jobs,
  onClose,
  onStarted,
}: {
  machine: Machine | null
  jobs: Job[]
  onClose: () => void
  onStarted: (r: Run) => void
}) {
  const [jobCard, setJobCard] = useState('')
  const [operator, setOperator] = useState('')
  const [shift, setShift] = useState<'day' | 'night'>(new Date().getHours() >= 20 || new Date().getHours() < 8 ? 'night' : 'day')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const candidates = jobs
    .filter((j) => ['planned', 'printing', 'design'].includes(j.status))
    .sort((a, b) => Number(b.machine_id === machine?.id) - Number(a.machine_id === machine?.id))
  const job = jobs.find((j) => j.job_card === jobCard)

  async function submit() {
    if (!machine) return
    setError(null)
    if (!jobCard || !operator.trim()) {
      setError('Choose a job and enter the operator name.')
      return
    }
    const body: RunStart = { job_card: jobCard, machine_id: machine.id, operator: operator.trim(), shift }
    setSaving(true)
    try {
      const res = await api.post<Run>('/api/production/runs/start', body)
      const run: Run =
        api.mode === 'mock'
          ? {
              ...res,
              ...body,
              client_name: job?.client_name ?? res.client_name,
              machine_name: machine.name,
              hour_rate: machine.hour_rate,
              start: appNowIso(),
              required_m: job?.required_m ?? res.required_m,
              printed_qty: 0,
              status: 'running',
            }
          : res
      onStarted(run)
      toast.success(`${run.job_card} started on ${machine.name}`)
      setJobCard('')
      setOperator('')
    } catch (e) {
      const { status, message } = describeError(e)
      setError(status ? `${status} · ${message}` : message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={!!machine} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Start run · {machine?.name}</DialogTitle>
          <DialogDescription>Pick the job card, the operator and the shift. The meter starts at zero.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Job card" htmlFor="rs-job" className="sm:col-span-2" hint={job ? `${job.client_name} · ${job.product} · ${formatNumber(job.order_qty)} labels · ${formatNumber(job.required_m, 1)} m required` : undefined}>
            <Select
              id="rs-job"
              size="touch"
              value={jobCard}
              onValueChange={setJobCard}
              placeholder="Choose job"
              options={candidates.map((j) => ({
                value: j.job_card,
                label: `${j.job_card} · ${j.client_name}${j.machine_id === machine?.id ? '' : ` (planned on ${j.machine_name})`}`,
              }))}
            />
          </Field>
          <Field label="Operator" htmlFor="rs-op">
            <Input id="rs-op" inputSize="touch" value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="e.g. Suresh Patil" />
          </Field>
          <Field label="Shift">
            <ShiftPicker value={shift} onChange={setShift} />
          </Field>
        </div>
        {job && job.status === 'design' && (
          <InlineAlert tone="warn">This job is still in design. Check plates are ready before you start.</InlineAlert>
        )}
        {error && <InlineAlert title="Could not start">{error}</InlineAlert>}
        <DialogFooter>
          <Button size="touch" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button size="touch" onClick={submit} loading={saving}>
            <Play aria-hidden /> Start run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ShiftPicker({ value, onChange }: { value: 'day' | 'night'; onChange: (v: 'day' | 'night') => void }) {
  return (
    <div role="radiogroup" aria-label="Shift" className="grid grid-cols-2 gap-2">
      {(['day', 'night'] as const).map((s) => (
        <button
          key={s}
          type="button"
          role="radio"
          aria-checked={value === s}
          onClick={() => onChange(s)}
          className={cn(
            'h-12 rounded-md border text-md font-medium capitalize transition-colors',
            value === s ? 'border-accent bg-accent-soft text-accent-soft-foreground' : 'border-border bg-surface text-foreground hover:bg-surface-muted',
          )}
        >
          {s}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* End run                                                             */
/* ------------------------------------------------------------------ */

export function EndRunDialog({
  run,
  job,
  initialCount,
  initialMetres,
  settings,
  onClose,
  onEnded,
}: {
  run: Run | null
  job: Job | undefined
  initialCount: number | null
  initialMetres: number | null
  settings: Settings | undefined
  onClose: () => void
  onEnded: (r: Run) => void
}) {
  return (
    <Dialog open={!!run} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="lg">
        {run && (
          <EndRunForm
            key={run.id}
            run={run}
            job={job}
            initialCount={initialCount}
            initialMetres={initialMetres}
            settings={settings}
            onClose={onClose}
            onEnded={onEnded}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function EndRunForm({
  run,
  job,
  initialCount,
  initialMetres,
  settings,
  onClose,
  onEnded,
}: {
  run: Run
  job: Job | undefined
  initialCount: number | null
  initialMetres: number | null
  settings: Settings | undefined
  onClose: () => void
  onEnded: (r: Run) => void
}) {
  const [printed, setPrinted] = useState(String(initialCount ?? run.printed_qty ?? ''))
  const [used, setUsed] = useState(initialMetres ? String(Math.round(initialMetres * 10) / 10) : '')
  const [downMin, setDownMin] = useState('0')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tol = settings?.wastage_tol ?? 0.15
  const overTol = settings?.overprod_tol ?? 0.1

  const p = Number(printed)
  const u = Number(used)
  const dm = Number(downMin)
  const required = run.required_m ?? 0
  const wPct = required > 0 && u > 0 ? (u - required) / required : null

  async function submit() {
    setError(null)
    if (!(p > 0) || !(u > 0)) {
      setError('Enter the printed count and the metres used from the meter.')
      return
    }
    if (dm > 0 && !reason) {
      setError('Choose a reason for the downtime.')
      return
    }
    const body: RunEnd = {
      printed_qty: p,
      used_m: u,
      stops: dm > 0 ? [...run.stops, { reason, minutes: dm }] : run.stops,
      end: appNowIso(),
    }
    setSaving(true)
    try {
      const res = await api.post<Run>(`/api/production/runs/${encodeURIComponent(run.id)}/end`, body)
      let result = res
      if (api.mode === 'mock') {
        const elapsed = (Date.now() - new Date(run.start).getTime()) / 3_600_000
        const hours = elapsed > 0 && elapsed < 16 ? Math.round(elapsed * 100) / 100 : (res.hours ?? 0)
        const req = run.required_m ?? res.required_m ?? 0
        const w = u - req
        const pct = req > 0 ? Math.round((w / req) * 10000) / 10000 : null
        result = {
          ...run,
          end: body.end ?? null,
          status: 'ended',
          printed_qty: p,
          used_m: u,
          required_m: req,
          wastage_m: Math.round(w * 100) / 100,
          wastage_pct: pct,
          wastage_flag: pct !== null && pct > tol,
          overprod_flag: job ? p > job.order_qty * (1 + overTol) : false,
          hours,
          crew_cost: Math.round(hours * run.hour_rate * 100) / 100,
          stops: body.stops ?? [],
        }
      }
      onEnded(result)
      toast.success(`${result.id} ended`)
    } catch (e) {
      const { status, message } = describeError(e)
      setError(status ? `${status} · ${message}` : message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>End run · {run.machine_name}</DialogTitle>
        <DialogDescription>
          {run.job_card} · {run.client_name} · {run.operator} ({run.shift} shift)
        </DialogDescription>
      </DialogHeader>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Printed count" htmlFor="re-printed" hint="From the press counter">
          <Input id="re-printed" inputSize="touch" type="number" inputMode="numeric" min={0} value={printed} onChange={(e) => setPrinted(e.target.value)} />
        </Field>
        <Field label="Metres used" htmlFor="re-used" hint={`Required for the job: ${formatNumber(required, 1)} m`}>
          <Input id="re-used" inputSize="touch" type="number" inputMode="decimal" min={0} value={used} onChange={(e) => setUsed(e.target.value)} />
        </Field>
        <Field label="Downtime (minutes)" htmlFor="re-down">
          <div className="flex items-center gap-2">
            <Button size="touch" variant="secondary" aria-label="Less downtime" onClick={() => setDownMin(String(Math.max(0, dm - 5)))}>
              −5
            </Button>
            <Input id="re-down" inputSize="touch" type="number" inputMode="numeric" min={0} value={downMin} onChange={(e) => setDownMin(e.target.value)} className="tabular text-center" />
            <Button size="touch" variant="secondary" aria-label="More downtime" onClick={() => setDownMin(String(dm + 5))}>
              +5
            </Button>
          </div>
        </Field>
        <Field label="Downtime reason" htmlFor="re-reason">
          <Select
            id="re-reason"
            size="touch"
            value={reason}
            onValueChange={setReason}
            placeholder={dm > 0 ? 'Choose reason' : 'No downtime'}
            disabled={!(dm > 0)}
            options={DOWNTIME_REASONS.map((r) => ({ value: r, label: r }))}
          />
        </Field>
      </div>
      {wPct !== null && (
        <InlineAlert tone={wPct > tol ? 'danger' : 'info'}>
          <span className="inline-flex items-center gap-1.5">
            <Timer className="size-4" aria-hidden />
            Wastage will be {formatPercent(wPct)} ({formatNumber(u - required, 1)} m){' '}
            {wPct > tol ? `: above the ${formatPercent(tol, { digits: 0 })} limit, the owner will be alerted.` : `: within the ${formatPercent(tol, { digits: 0 })} limit.`}
          </span>
        </InlineAlert>
      )}
      {error && <InlineAlert title="Could not end run">{error}</InlineAlert>}
      <DialogFooter>
        <Button size="touch" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button size="touch" onClick={submit} loading={saving}>
          <Pause aria-hidden /> End run
        </Button>
      </DialogFooter>
    </>
  )
}

