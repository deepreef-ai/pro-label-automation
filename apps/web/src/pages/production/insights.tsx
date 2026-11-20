import { useMemo } from 'react'
import { Layers, Sunrise } from 'lucide-react'
import type { MorningReport, Oee, PressSetup, Run } from '@contract/types'
import { useApi } from '@/lib/api'
import { formatDate, formatDateTime, formatINR, formatMonth, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  QueryState,
  StatusChip,
  TableSkeleton,
  toneForStatus,
} from '@/components/ui'
import { BarRow, Stat } from '@/pages/store/common'

/* Press setup ------------------------------------------------------- */

export function PressSetupCard({ jobCard }: { jobCard: string | null }) {
  const q = useApi<PressSetup>(jobCard ? `/api/production/press-setup/${encodeURIComponent(jobCard)}` : null)
  return (
    <Card>
      <CardHeader
        title="Press setup"
        description={jobCard ? `Units, colours and anilox for ${jobCard}` : 'Select a running press to see its job setup.'}
        actions={<Layers className="size-4 text-subtle-foreground" aria-hidden />}
      />
      <CardContent>
        {!jobCard ? (
          <EmptyState compact title="No job selected" description="Tap a press card above." />
        ) : (
          <QueryState query={q} loading={<TableSkeleton rows={5} columns={4} />}>
            {(s) => (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Stat label="Machine" value={s.machine_name} />
                  <Stat label="Web / repeat" value={`${s.web_width_mm} / ${s.repeat_mm} mm`} sub={`${s.ups_across} × ${s.ups_along} ups · die ${s.die_id ?? '—'}`} />
                  <Stat label="Target speed" value={`${s.speed_target_mpm} m/min`} />
                  <Stat label="Ink estimate" value={`${formatNumber(s.est_ink_kg, 2)} kg`} sub="feeds the ink pool share" />
                </div>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-surface-muted text-left text-xs text-muted-foreground">
                        <th className="px-3 py-2 font-medium">Unit</th>
                        <th className="px-3 py-2 font-medium">Colour</th>
                        <th className="px-3 py-2 text-right font-medium">Anilox</th>
                        <th className="px-3 py-2 font-medium">Plate</th>
                        <th className="px-3 py-2 font-medium">Ink item</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.units.map((u) => (
                        <tr key={u.unit} className="border-t border-border">
                          <td className="tabular px-3 py-2.5 font-medium">{u.unit}</td>
                          <td className="px-3 py-2.5">{u.colour}</td>
                          <td className="tabular px-3 py-2.5 text-right">
                            {u.anilox_lpi} lpi · {u.anilox_bcm} bcm
                          </td>
                          <td className="px-3 py-2.5 font-mono text-xs">{u.plate_id ?? '—'}</td>
                          <td className="px-3 py-2.5 font-mono text-xs">{u.ink_item_id ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {s.notes && <p className="text-sm text-muted-foreground">Note: {s.notes}</p>}
                <p className="text-xs text-subtle-foreground">
                  Updated {formatDateTime(s.updated_at)} by {s.updated_by}
                </p>
              </div>
            )}
          </QueryState>
        )}
      </CardContent>
    </Card>
  )
}

/* OEE ---------------------------------------------------------------- */

function Ring({ value, size = 104, label }: { value: number; size?: number; label: string }) {
  const r = (size - 12) / 2
  const c = 2 * Math.PI * r
  const tone = value >= 0.65 ? 'stroke-ok' : value >= 0.5 ? 'stroke-warn' : 'stroke-danger'
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${label} ${formatPercent(value)}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={10} className="fill-none stroke-surface-sunken" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={10}
          strokeLinecap="round"
          className={cn('fill-none transition-[stroke-dashoffset] duration-700', tone)}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value)))}
        />
      </svg>
      <span className="tabular absolute inset-0 flex items-center justify-center text-lg font-semibold text-foreground">
        {formatPercent(value, { digits: 0 })}
      </span>
    </div>
  )
}

export function OeeSection() {
  const q = useApi<Oee>('/api/production/oee')
  return (
    <Card>
      <CardHeader title="OEE by press" description="OEE = Availability × Performance × Quality." />
      <CardContent>
        <QueryState query={q} loading={<TableSkeleton rows={4} />}>
          {(o) => (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-4 rounded-lg bg-surface-muted p-4">
                <Ring value={o.plant_oee} size={84} label="Plant OEE" />
                <div>
                  <p className="text-sm text-muted-foreground">Plant OEE · {formatMonth(o.month)}</p>
                  <p className="text-sm text-muted-foreground">
                    {formatDate(o.from)} – {formatDate(o.to)}. World class is about 85%; 60% is a common label-plant level.
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {o.machines.map((m) => (
                  <div key={m.machine_id} className="flex gap-4 rounded-lg border border-border p-4">
                    <Ring value={m.oee} label={`${m.machine_name} OEE`} />
                    <div className="min-w-0 flex-1 space-y-2">
                      <p className="font-semibold text-foreground">{m.machine_name}</p>
                      <div className="tabular grid grid-cols-3 gap-2 text-sm">
                        <APQ k="A" v={m.availability} />
                        <APQ k="P" v={m.performance} />
                        <APQ k="Q" v={m.quality} />
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {formatNumber(m.run_hours)} of {formatNumber(m.planned_hours)} h run · {formatNumber(m.downtime_hours)} h down
                      </p>
                      <p className="truncate text-xs text-muted-foreground">Top loss: {m.top_loss}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </QueryState>
      </CardContent>
    </Card>
  )
}

function APQ({ k, v }: { k: string; v: number }) {
  return (
    <div className="rounded-sm bg-surface-muted px-2 py-1 text-center">
      <span className="text-xs text-muted-foreground">{k} </span>
      <span className="font-medium text-foreground">{formatPercent(v, { digits: 0 })}</span>
    </div>
  )
}

/* Morning report ------------------------------------------------------ */

export function MorningReportCard({ tol }: { tol: number }) {
  const q = useApi<MorningReport>('/api/production/morning-report')
  return (
    <Card>
      <CardHeader
        title="Morning report"
        description="Yesterday's production per press, ready at 8 am."
        actions={<Sunrise className="size-4 text-subtle-foreground" aria-hidden />}
      />
      <CardContent>
        <QueryState query={q} loading={<TableSkeleton rows={4} />}>
          {(m) => (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                For {formatDate(m.for_date)} · {formatNumber(m.totals.printed_qty)} labels · {formatNumber(m.totals.used_m, 1)} m used · wastage{' '}
                <span className={cn('font-medium', m.totals.wastage_pct > tol ? 'text-danger-foreground' : 'text-ok-foreground')}>
                  {formatPercent(m.totals.wastage_pct)}
                </span>{' '}
                · {formatNumber(m.totals.run_hours, 1)} h run
              </p>
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-muted text-left text-xs text-muted-foreground">
                      <th className="px-3 py-2 font-medium">Press</th>
                      <th className="px-3 py-2 font-medium">Jobs</th>
                      <th className="px-3 py-2 text-right font-medium">Printed</th>
                      <th className="px-3 py-2 text-right font-medium">Wastage</th>
                      <th className="px-3 py-2 text-right font-medium">Down</th>
                      <th className="px-3 py-2 text-right font-medium">MTD wastage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.machines.map((r) => (
                      <tr key={r.machine_id} className="border-t border-border">
                        <td className="px-3 py-2.5 font-medium">{r.machine_name}</td>
                        <td className="px-3 py-2.5 text-muted-foreground">{r.jobs.join(', ') || '—'}</td>
                        <td className="tabular px-3 py-2.5 text-right">{formatNumber(r.printed_qty)}</td>
                        <td className={cn('tabular px-3 py-2.5 text-right', r.wastage_pct > tol && 'font-medium text-danger-foreground')}>
                          {r.runs ? formatPercent(r.wastage_pct) : '—'}
                        </td>
                        <td className="tabular px-3 py-2.5 text-right">{r.downtime_min} min</td>
                        <td className="tabular px-3 py-2.5 text-right">{formatPercent(r.mtd_wastage_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="space-y-2">
                {m.highlights.map((h, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <StatusChip size="sm" tone={toneForStatus(h.severity)} className="mt-0.5 shrink-0">
                      {h.severity}
                    </StatusChip>
                    <span className="text-foreground">{h.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </QueryState>
      </CardContent>
    </Card>
  )
}

/* Downtime ------------------------------------------------------------ */

export function DowntimeCard({ runs }: { runs: Run[] }) {
  const rows = useMemo(() => {
    const m = new Map<string, { minutes: number; stops: number }>()
    for (const r of runs)
      for (const s of r.stops) {
        const cur = m.get(s.reason) ?? { minutes: 0, stops: 0 }
        m.set(s.reason, { minutes: cur.minutes + s.minutes, stops: cur.stops + 1 })
      }
    return [...m.entries()].sort((a, b) => b[1].minutes - a[1].minutes)
  }, [runs])
  const max = rows[0]?.[1].minutes ?? 1
  const total = rows.reduce((a, [, v]) => a + v.minutes, 0)
  const cost = runs.reduce((a, r) => a + (r.stops.reduce((x, s) => x + s.minutes, 0) / 60) * r.hour_rate, 0)
  return (
    <Card>
      <CardHeader
        title="Downtime by reason"
        description="Stops booked on runs this month."
        actions={<Badge tone="neutral">{total} min</Badge>}
      />
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState compact title="No stops booked" />
        ) : (
          <div className="space-y-4">
            {rows.map(([reason, v], i) => (
              <BarRow
                key={reason}
                label={`${reason} · ${v.stops} stop${v.stops === 1 ? '' : 's'}`}
                value={v.minutes}
                max={max}
                tone={i === 0 ? 'amber' : 'grey'}
                display={`${v.minutes} min`}
              />
            ))}
            <p className="border-t border-border pt-3 text-sm text-muted-foreground">
              Crew cost of these stops at machine hour rates: <span className="font-medium text-foreground">{formatINR(cost)}</span>
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
