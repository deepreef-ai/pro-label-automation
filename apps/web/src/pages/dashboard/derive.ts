/**
 * Dashboard data shaping. No money maths here: all rupee values come straight from the API.
 *
 * MOCK-ONLY behaviour (documented on purpose):
 *   The alerts fixture was computed with wastage_tol = 15%. When the owner saves a different
 *   wastage tolerance on Settings (kept in `pages/settings/store.ts`), `applyMockWastageTolerance`
 *   re-derives the job wastage alerts client-side from the runs + jobs fixtures so the demo
 *   "15% -> 10% adds alerts" works without a backend. Job wastage % uses ended press runs
 *   (used - required) / required; for jobs still on press with no ended run it uses material
 *   issued vs required as a stand-in. In live mode none of this runs: the backend recalculates
 *   alerts through core.rules.
 */
import type { Alert, DashboardSummary, Job, Machine, Oee, Run } from '@contract/types'
import { formatPercent } from '@/lib/format'

/** Job-wise profit rows the live API adds to the summary (`top_jobs` / `bottom_jobs`; not in openapi.yaml yet). */
export interface LowProfitJob {
  job_card: string
  client_name: string
  product?: string
  revenue: number
  profit: number
  margin_pct: number
  link?: string
  is_demo?: boolean
}

/** One day of the live API's `trend_30d`. */
export interface DailyPoint {
  date: string
  label?: string
  revenue: number
  profit: number
}

/** Per-machine figures for the period from the live API's summary (`machines`). */
export interface SummaryMachine {
  machine_id: string
  machine_name: string
  type: Machine['type']
  runs: number
  printed_qty: number
  run_hours: number
  wastage_pct: number | null
  oee: number | null
  running?: boolean
}

/** Extra fields the live backend returns on top of the contract's DashboardSummary (mock fixtures lack them). */
export type SummaryExt = DashboardSummary & {
  top_jobs?: LowProfitJob[]
  bottom_jobs?: LowProfitJob[]
  trend_30d?: DailyPoint[]
  machines?: SummaryMachine[]
  is_demo?: boolean
}

/** Lowest-profit jobs of the period from the summary's job-wise rows (null when the API has none). */
export function lowProfitJobs(summary: SummaryExt | undefined): LowProfitJob[] | null {
  if (!summary || (!summary.top_jobs && !summary.bottom_jobs)) return null
  const seen = new Map<string, LowProfitJob>()
  for (const j of [...(summary.bottom_jobs ?? []), ...(summary.top_jobs ?? [])]) seen.set(j.job_card, j)
  return [...seen.values()].sort((a, b) => a.profit - b.profit).slice(0, 10)
}

export type DashAlert = Alert & { derived?: boolean }

/** Tolerance the alerts fixture was generated with. */
export const FIXTURE_WASTAGE_TOL = 0.15

export interface JobWastage {
  pct: number
  basis: 'runs' | 'issued'
}

export function jobWastage(job: Job, runs: Run[]): JobWastage | null {
  const ended = runs.filter(
    (r) => r.job_card === job.job_card && r.machine_type === 'press' && r.used_m != null && r.required_m != null,
  )
  if (ended.length) {
    const req = ended.reduce((s, r) => s + (r.required_m ?? 0), 0)
    const used = ended.reduce((s, r) => s + (r.used_m ?? 0), 0)
    return req > 0 ? { pct: (used - req) / req, basis: 'runs' } : null
  }
  if (job.printed_qty > 0 && job.issued_m > 0 && job.required_m > 0) {
    return { pct: (job.issued_m - job.required_m) / job.required_m, basis: 'issued' }
  }
  return null
}

const WASTAGE_TITLE = /^(JC-\d+) wastage/i

/** Mock mode only: add / drop job wastage alerts for a changed tolerance. See file header. */
export function applyMockWastageTolerance(alerts: Alert[], tol: number, jobs: Job[], runs: Run[]): DashAlert[] {
  if (Math.abs(tol - FIXTURE_WASTAGE_TOL) < 1e-9) return alerts
  const over = new Map<string, { job: Job; w: JobWastage }>()
  for (const job of jobs) {
    const w = jobWastage(job, runs)
    if (w && w.pct > tol) over.set(job.job_card, { job, w })
  }
  const kept: DashAlert[] = []
  const covered = new Set<string>()
  for (const a of alerts) {
    const m = WASTAGE_TITLE.exec(a.title)
    if (m) {
      if (!over.has(m[1])) continue // no longer above the (raised) limit
      covered.add(m[1])
      kept.push({ ...a, title: a.title.replace(/\(limit [^)]*\)/, `(limit ${formatPercent(tol, { digits: 0 })})`) })
    } else kept.push(a)
  }
  const now = new Date().toISOString()
  const added: DashAlert[] = []
  for (const [jc, { job, w }] of over) {
    if (covered.has(jc)) continue
    added.push({
      id: `MOCK-W-${jc}`,
      severity: w.pct > tol * 1.5 ? 'high' : 'medium',
      area: 'production',
      title: `${jc} wastage ${formatPercent(w.pct)} (limit ${formatPercent(tol, { digits: 0 })})`,
      detail: `${job.client_name} · ${job.product}. ${
        w.basis === 'runs' ? 'From ended press runs.' : 'Material issued vs required; run still open.'
      }`,
      link: `/jobs/${jc}`,
      created_at: now,
      derived: true,
    })
  }
  return [...added, ...kept]
}

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 } as const

export function sortAlerts(alerts: DashAlert[]): DashAlert[] {
  return [...alerts].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || b.created_at.localeCompare(a.created_at),
  )
}

export interface MachineRow {
  id: string
  name: string
  type: Machine['type']
  oee: number | null
  wastage: number | null
  hours: number
  hour_rate: number
  top_loss: string | null
  is_demo: boolean
}

/** All machines, joined with OEE (press only) and wastage. Live: OEE, wastage and hours come from the
 *  summary's per-machine rows for the selected period; mock: wastage from ended press runs. */
export function machineRows(
  machines: Machine[],
  oee: Oee | undefined,
  runs: Run[],
  periodRows?: SummaryMachine[],
): MachineRow[] {
  return machines.map((m) => {
    const o = oee?.machines.find((x) => x.machine_id === m.id)
    if (periodRows) {
      const p = periodRows.find((x) => x.machine_id === m.id)
      return {
        id: m.id,
        name: m.name,
        type: m.type,
        oee: m.type === 'press' ? (p?.oee ?? o?.oee ?? null) : null,
        wastage: m.type === 'press' && p && p.run_hours > 0 ? (p.wastage_pct ?? null) : null,
        hours: p?.run_hours ?? 0,
        hour_rate: o?.hour_rate ?? m.hour_rate,
        top_loss: o?.top_loss ?? null,
        is_demo: m.is_demo,
      }
    }
    const ended = runs.filter((r) => r.machine_id === m.id && r.used_m != null && r.required_m)
    const req = ended.reduce((s, r) => s + (r.required_m ?? 0), 0)
    const used = ended.reduce((s, r) => s + (r.used_m ?? 0), 0)
    return {
      id: m.id,
      name: m.name,
      type: m.type,
      oee: o?.oee ?? null,
      wastage: m.type === 'press' && req > 0 ? (used - req) / req : null,
      hours: o?.run_hours ?? m.hours_run_month,
      hour_rate: o?.hour_rate ?? m.hour_rate,
      top_loss: o?.top_loss ?? null,
      is_demo: m.is_demo,
    }
  })
}

export interface ProfitRiskRow {
  job_card: string
  client_name: string
  product: string
  po_value: number
  wastage: JobWastage | null
  flags: Job['flags']
  status: Job['status']
  is_demo: boolean
}

/**
 * Fallback for the "lowest-profit jobs" table while the summary has no job-wise profit:
 * jobs ranked by profit risk (flags, then wastage), showing API values only.
 */
export function profitRiskRows(jobs: Job[], runs: Run[]): ProfitRiskRow[] {
  return jobs
    .map((j) => ({
      job_card: j.job_card,
      client_name: j.client_name,
      product: j.product,
      po_value: j.po_value,
      wastage: jobWastage(j, runs),
      flags: j.flags,
      status: j.status,
      is_demo: j.is_demo,
    }))
    .sort((a, b) => b.flags.length - a.flags.length || (b.wastage?.pct ?? -1) - (a.wastage?.pct ?? -1))
    .slice(0, 10)
}

/** Previous-points average for KPI deltas (summary has no "previous period" fields). */
export function trendDelta(values: number[]): number | null {
  if (values.length < 2) return null
  const last = values[values.length - 1]
  const prior = values.slice(0, -1)
  const avg = prior.reduce((s, v) => s + v, 0) / prior.length
  return avg ? (last - avg) / avg : null
}
