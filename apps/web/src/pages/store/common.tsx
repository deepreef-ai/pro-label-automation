import type { ReactNode } from 'react'
import { AlertTriangle, Info } from 'lucide-react'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { appToday } from '@/lib/clock'

/** Turn any thrown value into `{ status, message }` for an inline error. */
export function describeError(err: unknown): { status: number | null; message: string } {
  if (err instanceof ApiError) return { status: err.status || null, message: err.message }
  if (err instanceof Error) return { status: null, message: err.message }
  return { status: null, message: String(err) }
}

/** Inline alert used inside forms and panels. */
export function InlineAlert({
  tone = 'danger',
  title,
  children,
  className,
}: {
  tone?: 'danger' | 'warn' | 'info'
  title?: ReactNode
  children?: ReactNode
  className?: string
}) {
  const Icon = tone === 'info' ? Info : AlertTriangle
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cn(
        'flex gap-3 rounded-md border px-3.5 py-3 text-sm',
        tone === 'danger' && 'border-danger/25 bg-danger-soft text-danger-foreground',
        tone === 'warn' && 'border-warn/25 bg-warn-soft text-warn-foreground',
        tone === 'info' && 'border-info/20 bg-info-soft text-info-foreground',
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 space-y-0.5">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div>{children}</div>}
      </div>
    </div>
  )
}

/** Small label/value pair. */
export function Stat({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0', className)}>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="tabular mt-0.5 text-lg font-semibold text-foreground">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

const barTone = {
  accent: 'bg-chart-1',
  blue: 'bg-chart-2',
  amber: 'bg-chart-3',
  green: 'bg-chart-4',
  grey: 'bg-chart-5',
  danger: 'bg-danger',
} as const

export type BarTone = keyof typeof barTone

/** Horizontal bar row: label, track, value. Calm, token-coloured, no chart library needed. */
export function BarRow({
  label,
  value,
  max,
  display,
  tone = 'accent',
  hint,
}: {
  label: ReactNode
  value: number
  max: number
  display: ReactNode
  tone?: BarTone
  hint?: ReactNode
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="min-w-0 truncate text-foreground">{label}</span>
        <span className="tabular shrink-0 font-medium text-foreground">{display}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
        <div className={cn('h-full rounded-full', barTone[tone])} style={{ width: `${pct}%` }} />
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** Barcode-style rendering for roll IDs (decorative bars + mono text). */
export function BarcodeId({ id }: { id: string }) {
  // Deterministic bar widths from the characters of the ID.
  const bars = Array.from(id.replace(/\W/g, '')).flatMap((ch) => {
    const c = ch.charCodeAt(0)
    return [1 + (c % 3), 1 + ((c >> 2) % 2)]
  })
  let x = 0
  const rects = bars.map((w, i) => {
    const r = i % 2 === 0 ? <rect key={i} x={x} y={0} width={w} height={18} /> : null
    x += w + 1
    return r
  })
  return (
    <span className="inline-flex items-center gap-2">
      <svg
        viewBox={`0 0 ${x} 18`}
        className="h-[18px] w-auto shrink-0 fill-foreground"
        style={{ width: Math.min(x, 96) }}
        preserveAspectRatio="none"
        aria-hidden
      >
        {rects}
      </svg>
      <span className="font-mono text-sm tracking-tight text-foreground">{id}</span>
    </span>
  )
}

/** ISO date `YYYY-MM-DD` for today (local). */
export function todayIso(): string {
  return appToday() // the server's demo day (see lib/clock)
}

/** Whole days between two ISO dates (b - a). */
export function daysBetween(a: string, b: string): number {
  const pa = new Date(`${a}T00:00:00`)
  const pb = new Date(`${b}T00:00:00`)
  return Math.round((pb.getTime() - pa.getTime()) / 86_400_000)
}

/**
 * Rows saved on this screen first, then the list from the API. In live mode the API list is refetched
 * after a save, so a saved row that is already in it is dropped here (no duplicates).
 */
export function withAdded<T extends { id: string }>(added: T[], rows: T[]): T[] {
  if (!added.length) return rows
  const ids = new Set(rows.map((r) => r.id))
  return [...added.filter((a) => !ids.has(a.id)), ...rows]
}
