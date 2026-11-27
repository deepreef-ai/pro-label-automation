import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Step {
  key: string
  label: string
}

/**
 * Horizontal stage tracker (Design: Artwork → Proof → Approval → Plates).
 * `current` is the key of the active step; earlier steps show as done.
 * Pass `current="__done__"` (or a key not in the list with `complete`) to show all done.
 */
export function ProgressSteps({
  steps,
  current,
  complete,
  size = 'md',
  className,
}: {
  steps: Step[]
  current?: string
  complete?: boolean
  size?: 'sm' | 'md'
  className?: string
}) {
  const idx = complete ? steps.length : Math.max(0, steps.findIndex((s) => s.key === current))
  return (
    <ol className={cn('flex w-full items-center', className)} aria-label="Progress">
      {steps.map((step, i) => {
        const done = i < idx
        const active = i === idx
        return (
          <li key={step.key} className={cn('flex items-center', i < steps.length - 1 && 'flex-1')}>
            <div className="flex items-center gap-2" aria-current={active ? 'step' : undefined}>
              <span
                className={cn(
                  'flex shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular transition-colors',
                  size === 'sm' ? 'size-5 text-[10px]' : 'size-7',
                  done && 'border-accent bg-accent text-accent-foreground',
                  active && 'border-accent bg-accent-soft text-accent-soft-foreground',
                  !done && !active && 'border-border-strong bg-surface text-subtle-foreground',
                )}
              >
                {done ? <Check className={size === 'sm' ? 'size-3' : 'size-3.5'} strokeWidth={3} /> : i + 1}
              </span>
              <span
                className={cn(
                  'whitespace-nowrap',
                  size === 'sm' ? 'text-xs' : 'text-sm',
                  active ? 'font-semibold text-foreground' : done ? 'text-foreground' : 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <span aria-hidden className={cn('mx-3 h-px flex-1', done ? 'bg-accent' : 'bg-border')} />
            )}
          </li>
        )
      })}
    </ol>
  )
}
