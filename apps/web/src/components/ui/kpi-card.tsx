import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatINRShort, formatPercent } from '@/lib/format'
import { Card } from './card'
import { Skeleton } from './skeleton'

export interface KpiCardProps {
  label: ReactNode
  /** Number: formatted as short INR (₹4.2 L). Pass a string/ReactNode to format yourself. */
  value: number | ReactNode
  /** Change as a ratio (0.042 = +4.2%). */
  delta?: number | null
  /** e.g. "vs last month" */
  deltaLabel?: ReactNode
  /** Set when a rise is bad (costs, wastage, overdue). */
  invertDelta?: boolean
  icon?: LucideIcon
  /** Small chart under the number, e.g. <Sparkline data={…} /> */
  sparkline?: ReactNode
  footer?: ReactNode
  loading?: boolean
  onClick?: () => void
  className?: string
}

export function KpiCard({
  label,
  value,
  delta,
  deltaLabel,
  invertDelta,
  icon: Icon,
  sparkline,
  footer,
  loading,
  onClick,
  className,
}: KpiCardProps) {
  const hasDelta = typeof delta === 'number' && Number.isFinite(delta)
  const up = hasDelta && delta! > 0
  const flat = hasDelta && delta === 0
  const good = flat ? null : invertDelta ? !up : up
  const DeltaIcon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight

  return (
    <Card
      interactive={!!onClick}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onClick()
              }
            }
          : undefined
      }
      className={cn('flex flex-col gap-3 p-5', className)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
        {Icon && <Icon className="size-4 text-subtle-foreground" aria-hidden />}
      </div>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-3.5 w-20" />
        </div>
      ) : (
        <>
          <div className="flex items-end justify-between gap-3">
            <div className="tabular text-3xl font-semibold leading-none tracking-tight text-foreground">
              {typeof value === 'number' ? formatINRShort(value) : value}
            </div>
            {sparkline && <div className="h-10 w-24 shrink-0">{sparkline}</div>}
          </div>
          {(hasDelta || deltaLabel) && (
            <div className="flex items-center gap-1.5 text-sm">
              {hasDelta && (
                <span
                  className={cn(
                    'tabular inline-flex items-center gap-0.5 font-medium',
                    good === null ? 'text-muted-foreground' : good ? 'text-ok-foreground' : 'text-danger-foreground',
                  )}
                >
                  <DeltaIcon className="size-3.5" aria-hidden />
                  {formatPercent(delta, { signed: true })}
                </span>
              )}
              {deltaLabel && <span className="text-muted-foreground">{deltaLabel}</span>}
            </div>
          )}
        </>
      )}
      {footer && <div className="border-t border-border pt-3 text-sm text-muted-foreground">{footer}</div>}
    </Card>
  )
}
