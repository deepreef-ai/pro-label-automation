import { CheckCheck, ClipboardList, Mail, MessageCircle } from 'lucide-react'
import type { OutboxItem } from '@contract/types'
import { Badge, EmptyState, SheetContent, StatusChip, toneForStatus } from '@/components/ui'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const STATUS_LABEL: Record<OutboxItem['status'], string> = {
  draft: 'Waiting for approval',
  approved: 'Approved',
  sent: 'Sent (simulated)',
  failed: 'Failed',
}

function Bubble({ item }: { item: OutboxItem }) {
  const time = formatDateTime(item.sent_at ?? item.created_at).split(', ')[1] ?? ''
  if (item.channel === 'whatsapp') {
    return (
      <div className="ml-auto max-w-[85%] rounded-lg rounded-tr-sm border border-ok/20 bg-ok-soft px-3 py-2 text-sm text-foreground">
        <p className="whitespace-pre-wrap">{item.body}</p>
        <div className="mt-1 flex items-center justify-end gap-1 text-2xs text-muted-foreground">
          {time}
          {item.status === 'sent' && <CheckCheck className="size-3.5 text-info" aria-label="Delivered (simulated)" />}
        </div>
      </div>
    )
  }
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-sm">
      {item.subject && <div className="font-medium text-foreground">{item.subject}</div>}
      <p className="mt-0.5 whitespace-pre-wrap text-muted-foreground">{item.body}</p>
    </div>
  )
}

export function OutboxSheet({ items }: { items: OutboxItem[] }) {
  return (
    <SheetContent
      title="Outbox"
      description="Messages and tasks created by approved findings. Nothing leaves this laptop in the demo."
      className="max-w-lg"
    >
      {items.length === 0 ? (
        <EmptyState compact title="Outbox is empty" description="Approve a finding with drafted messages to see them here." />
      ) : (
        <ul className="space-y-3">
          {items.map((o) => {
            const Icon = o.channel === 'whatsapp' ? MessageCircle : o.channel === 'email' ? Mail : ClipboardList
            return (
              <li key={o.id} className="rounded-lg border border-border bg-surface-muted p-3">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-surface text-muted-foreground">
                      <Icon className="size-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-foreground">{o.to}</div>
                      <div className="text-2xs text-muted-foreground">
                        {o.id} · {o.finding_id ?? o.agent}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {o.simulated && (
                      <Badge size="sm" tone="neutral" className={cn('border-dashed uppercase tracking-wide')}>
                        Simulated
                      </Badge>
                    )}
                    <StatusChip size="sm" tone={o.status === 'sent' ? 'ok' : toneForStatus(o.status)}>
                      {STATUS_LABEL[o.status]}
                    </StatusChip>
                  </div>
                </div>
                <Bubble item={o} />
              </li>
            )
          })}
        </ul>
      )}
    </SheetContent>
  )
}
