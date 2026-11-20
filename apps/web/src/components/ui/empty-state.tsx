import type { ReactNode } from 'react'
import { Inbox, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  icon?: LucideIcon
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
  /** compact: for inside cards / tables */
  compact?: boolean
  /** Render the title as a heading (e.g. 'h1' on a full-page state like 404). Default: p */
  titleAs?: 'p' | 'h1' | 'h2' | 'h3'
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
  compact,
  titleAs: Title = 'p',
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 px-6 py-10' : 'gap-3 px-6 py-16',
        className,
      )}
    >
      <div
        className={cn(
          'flex items-center justify-center rounded-lg border border-border bg-surface-muted text-muted-foreground',
          compact ? 'size-10' : 'size-12',
        )}
      >
        <Icon className={compact ? 'size-5' : 'size-6'} strokeWidth={1.75} aria-hidden />
      </div>
      <div className="max-w-sm space-y-1">
        <Title className={cn('font-semibold text-foreground', compact ? 'text-base' : 'text-md')}>{title}</Title>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}
