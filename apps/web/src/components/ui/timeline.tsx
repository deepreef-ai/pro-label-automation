import type { ReactNode } from 'react'
import { Check, Circle, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatDate } from '@/lib/format'

export type TimelineState = 'done' | 'current' | 'pending' | 'warn' | 'danger'

export interface TimelineItem {
  id?: string
  title: ReactNode
  /** ISO date/datetime or preformatted text */
  date?: string
  description?: ReactNode
  /** Right-aligned value (e.g. ₹ amount, qty) */
  meta?: ReactNode
  state?: TimelineState
  icon?: LucideIcon
}

const dot: Record<TimelineState, string> = {
  done: 'border-accent bg-accent text-accent-foreground',
  current: 'border-accent bg-surface text-accent ring-4 ring-accent-soft',
  pending: 'border-border-strong bg-surface text-subtle-foreground',
  warn: 'border-warn bg-warn-soft text-warn-foreground',
  danger: 'border-danger bg-danger-soft text-danger-foreground',
}

/** Vertical journey (Job 360: enquiry → quote → job → … → invoice → paid). */
export function Timeline({ items, className }: { items: TimelineItem[]; className?: string }) {
  return (
    <ol className={cn('relative', className)}>
      {items.map((item, i) => {
        const state = item.state ?? 'done'
        const Icon = item.icon ?? (state === 'done' ? Check : Circle)
        const last = i === items.length - 1
        return (
          <li key={item.id ?? i} className="relative flex gap-4 pb-6 last:pb-0">
            {!last && (
              <span
                aria-hidden
                className={cn(
                  'absolute top-7 bottom-0 left-[13px] w-px',
                  state === 'done' ? 'bg-accent/40' : 'bg-border',
                )}
              />
            )}
            <span
              className={cn(
                'relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full border-2',
                dot[state],
              )}
            >
              <Icon className={cn(state === 'pending' || state === 'current' ? 'size-2.5 fill-current' : 'size-3.5')} strokeWidth={2.5} aria-hidden />
            </span>
            <div className="flex min-w-0 flex-1 items-start justify-between gap-4 pt-0.5">
              <div className="min-w-0">
                <div className={cn('text-base font-medium', state === 'pending' ? 'text-muted-foreground' : 'text-foreground')}>
                  {item.title}
                </div>
                {item.date && (
                  <div className="text-xs text-muted-foreground">
                    {/^\d{4}-\d{2}-\d{2}/.test(item.date) ? formatDate(item.date) : item.date}
                  </div>
                )}
                {item.description && <div className="mt-1 text-sm text-muted-foreground">{item.description}</div>}
              </div>
              {item.meta && <div className="tabular shrink-0 text-base font-medium text-foreground">{item.meta}</div>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
