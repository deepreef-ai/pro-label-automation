import type { ReactNode } from 'react'
import { Hammer, type LucideIcon } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui'

/** Placeholder used by pages that are not built yet. Replace the whole page file when you build it. */
export function ComingSoon({
  title,
  subtitle,
  task,
  icon = Hammer,
  features,
}: {
  title: string
  subtitle?: ReactNode
  task: string
  icon?: LucideIcon
  features?: string[]
}) {
  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      <Card>
        <EmptyState
          icon={icon}
          title={`Coming in task ${task}`}
          description={
            features && features.length > 0 ? (
              <span className="mt-2 flex flex-wrap justify-center gap-1.5">
                {features.map((f) => (
                  <span
                    key={f}
                    className="rounded-full border border-border bg-surface-muted px-2.5 py-0.5 text-xs text-muted-foreground"
                  >
                    {f}
                  </span>
                ))}
              </span>
            ) : (
              'This screen is being built.'
            )
          }
        />
      </Card>
    </>
  )
}
