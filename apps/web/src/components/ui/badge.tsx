import type { HTMLAttributes, ReactNode } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

export type Tone = 'ok' | 'warn' | 'danger' | 'info' | 'neutral' | 'accent'

export const badgeVariants = cva(
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-medium leading-none tabular',
  {
    variants: {
      tone: {
        ok: 'border-ok/20 bg-ok-soft text-ok-foreground',
        warn: 'border-warn/25 bg-warn-soft text-warn-foreground',
        danger: 'border-danger/20 bg-danger-soft text-danger-foreground',
        info: 'border-info/20 bg-info-soft text-info-foreground',
        neutral: 'border-border bg-neutral-soft text-neutral-foreground',
        accent: 'border-accent/20 bg-accent-soft text-accent-soft-foreground',
      },
      size: {
        sm: 'h-5 px-2 text-2xs',
        md: 'h-6 px-2.5 text-xs',
      },
    },
    defaultVariants: { tone: 'neutral', size: 'md' },
  },
)

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone, size }), className)} {...props} />
}

const dotTone: Record<Tone, string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  danger: 'bg-danger',
  info: 'bg-info',
  neutral: 'bg-subtle-foreground',
  accent: 'bg-accent',
}

/** Status pill with a coloured dot: <StatusChip tone="ok">Approved</StatusChip> */
export function StatusChip({
  tone = 'neutral',
  children,
  className,
  size,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  size?: 'sm' | 'md'
}) {
  return (
    <Badge tone={tone} size={size} className={className}>
      <span className={cn('size-1.5 rounded-full', dotTone[tone])} aria-hidden />
      {children}
    </Badge>
  )
}

/** Map common status words from the API to a tone. */
export function toneForStatus(status: string | null | undefined): Tone {
  const s = (status ?? '').toLowerCase().replace(/[\s-]+/g, '_')
  if (/(approved|done|ok|paid|won|complete|completed|delivered|dispatched|active|running|in_stock|pass|closed)/.test(s))
    return 'ok'
  if (/(hold|pending|due|warn|medium|partial|rework|draft|proof|open|in_progress|waiting|low_stock|not_due)/.test(s))
    return 'warn'
  if (/(reject|rejected|lost|overdue|locked|high|fail|failed|short|shortage|blocked|danger|90_plus|61_90)/.test(s))
    return 'danger'
  if (/(new|info|quote|quoted|enquiry|planned|low)/.test(s)) return 'info'
  return 'neutral'
}

/** "DEMO" pill for rows with is_demo: true. Renders nothing otherwise. */
export function DemoBadge({ show = true, className }: { show?: boolean | null; className?: string }) {
  if (!show) return null
  return (
    <span
      title="Synthetic demo data"
      className={cn(
        'inline-flex h-[18px] items-center rounded-sm border border-dashed border-border-strong px-1.5 text-[10px] font-semibold uppercase tracking-wider text-subtle-foreground',
        className,
      )}
    >
      Demo
    </span>
  )
}
