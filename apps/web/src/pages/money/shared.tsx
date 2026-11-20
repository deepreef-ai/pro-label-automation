import type { ReactNode } from 'react'
import { Lock } from 'lucide-react'
import type { DebtorRow } from '@contract/types'
import { StatusChip } from '@/components/ui'
import { formatDateShort, formatINRShort } from '@/lib/format'
import { cn } from '@/lib/utils'

export type BucketKey = 'not_due' | '1_30' | '31_60' | '61_90' | '90_plus'
export type Buckets = Record<BucketKey, number>

export const BUCKETS: { key: BucketKey; label: string; swatch: string }[] = [
  { key: 'not_due', label: 'Not due', swatch: 'bg-chart-4' },
  { key: '1_30', label: '1–30 days', swatch: 'bg-chart-3' },
  { key: '31_60', label: '31–60 days', swatch: 'bg-warn' },
  { key: '61_90', label: '61–90 days', swatch: 'bg-danger/70' },
  { key: '90_plus', label: '90+ days', swatch: 'bg-danger' },
]

/** Horizontal stacked bar of ageing buckets. */
export function AgeingBar({
  buckets,
  height = 'h-3',
  showLegend = false,
  className,
}: {
  buckets: Buckets
  height?: string
  showLegend?: boolean
  className?: string
}) {
  const total = BUCKETS.reduce((s, b) => s + (buckets[b.key] ?? 0), 0)
  return (
    <div className={cn('space-y-3', className)}>
      <div
        className={cn('flex w-full overflow-hidden rounded-sm bg-surface-muted', height)}
        role="img"
        aria-label={BUCKETS.map((b) => `${b.label} ${formatINRShort(buckets[b.key])}`).join(', ')}
      >
        {total > 0 &&
          BUCKETS.map((b) => {
            const v = buckets[b.key] ?? 0
            if (v <= 0) return null
            return (
              <div
                key={b.key}
                className={cn(b.swatch, 'h-full border-r-2 border-surface last:border-r-0')}
                style={{ width: `${(v / total) * 100}%` }}
                title={`${b.label}: ${formatINRShort(v)}`}
              />
            )
          })}
      </div>
      {showLegend && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-5">
          {BUCKETS.map((b) => (
            <div key={b.key} className="min-w-0">
              <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className={cn('size-2.5 rounded-sm', b.swatch)} aria-hidden />
                {b.label}
              </dt>
              <dd className="tabular mt-0.5 text-md font-semibold text-foreground">{formatINRShort(buckets[b.key])}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

export function LockChip({ row }: { row: Pick<DebtorRow, 'lock_status' | 'locks_on' | 'locked_since'> }) {
  if (row.lock_status === 'locked')
    return (
      <StatusChip tone="danger">
        <Lock className="size-3" aria-hidden />
        Locked{row.locked_since ? ` since ${formatDateShort(row.locked_since)}` : ''}
      </StatusChip>
    )
  if (row.lock_status === 'at_risk')
    return <StatusChip tone="warn">Locks {row.locks_on ? formatDateShort(row.locks_on) : 'soon'}</StatusChip>
  return <StatusChip tone="ok">OK</StatusChip>
}

/** Days between two ISO dates (b - a). */
export function daysBetween(a: string, b: string): number {
  const pa = Date.parse(a.slice(0, 10) + 'T00:00:00Z')
  const pb = Date.parse(b.slice(0, 10) + 'T00:00:00Z')
  return Math.round((pb - pa) / 86_400_000)
}

export function Stat({ label, value, hint, tone }: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: 'danger' | 'warn' | 'ok' }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          'tabular mt-1 text-xl font-semibold text-foreground',
          tone === 'danger' && 'text-danger-foreground',
          tone === 'warn' && 'text-warn-foreground',
          tone === 'ok' && 'text-ok-foreground',
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}
