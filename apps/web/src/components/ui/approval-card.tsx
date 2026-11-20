import { useState, type ReactNode } from 'react'
import { Check, ExternalLink, Pencil, Sparkles, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { formatRelative } from '@/lib/format'
import { Button } from './button'
import { Card } from './card'
import { StatusChip, type Tone } from './badge'

export type Severity = 'high' | 'medium' | 'low'

const severityTone: Record<Severity, Tone> = { high: 'danger', medium: 'warn', low: 'info' }
const severityLabel: Record<Severity, string> = { high: 'High', medium: 'Medium', low: 'Low' }

export interface Evidence {
  label: string
  /** In-app path (/jobs/JC-1001) or external URL */
  link?: string | null
}

export interface ApprovalCardProps {
  /** Who raised it: agent name or person */
  who: ReactNode
  /** What it found (title) */
  what: ReactNode
  /** Longer explanation */
  detail?: ReactNode
  /** Proof: evidence links */
  evidence?: Evidence[]
  /** Suggested action, in plain words */
  suggestedAction?: ReactNode
  severity?: Severity
  createdAt?: string
  status?: 'open' | 'done' | 'rejected'
  onApprove?: () => void | Promise<void>
  onReject?: () => void | Promise<void>
  onEdit?: () => void
  className?: string
}

/** Human-in-the-loop card: who / what / proof / suggested action + Approve, Reject, Edit. */
export function ApprovalCard({
  who,
  what,
  detail,
  evidence,
  suggestedAction,
  severity = 'medium',
  createdAt,
  status = 'open',
  onApprove,
  onReject,
  onEdit,
  className,
}: ApprovalCardProps) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const run = async (kind: 'approve' | 'reject', fn?: () => void | Promise<void>) => {
    if (!fn) return
    setBusy(kind)
    try {
      await fn()
    } finally {
      setBusy(null)
    }
  }
  const decided = status !== 'open'

  return (
    <Card className={cn('flex flex-col', decided && 'opacity-80', className)}>
      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <div className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
          <span className="flex size-6 items-center justify-center rounded-md bg-accent-soft text-accent-soft-foreground">
            <Sparkles className="size-3.5" aria-hidden />
          </span>
          <span className="truncate font-medium text-foreground">{who}</span>
          {createdAt && <span className="shrink-0">· {formatRelative(createdAt)}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status === 'done' && <StatusChip tone="ok">Approved</StatusChip>}
          {status === 'rejected' && <StatusChip tone="neutral">Rejected</StatusChip>}
          <StatusChip tone={severityTone[severity]}>{severityLabel[severity]}</StatusChip>
        </div>
      </div>

      <div className="space-y-3 px-5 pt-3 pb-4">
        <h3 className="text-md font-semibold text-foreground">{what}</h3>
        {detail && <div className="text-base text-muted-foreground">{detail}</div>}

        {evidence && evidence.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium tracking-wide text-subtle-foreground uppercase">Proof</div>
            <ul className="flex flex-wrap gap-2">
              {evidence.map((ev, i) => (
                <li key={i}>
                  {ev.link ? (
                    ev.link.startsWith('/') ? (
                      <Link
                        to={ev.link}
                        className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-muted px-2 py-1 text-sm text-foreground hover:border-border-strong"
                      >
                        {ev.label}
                        <ExternalLink className="size-3 text-muted-foreground" aria-hidden />
                      </Link>
                    ) : (
                      <a
                        href={ev.link}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-muted px-2 py-1 text-sm text-foreground hover:border-border-strong"
                      >
                        {ev.label}
                        <ExternalLink className="size-3 text-muted-foreground" aria-hidden />
                      </a>
                    )
                  ) : (
                    <span className="inline-flex rounded-md border border-border bg-surface-muted px-2 py-1 text-sm text-foreground">
                      {ev.label}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {suggestedAction && (
          <div className="rounded-md border border-accent/20 bg-accent-soft px-3 py-2.5">
            <div className="text-xs font-medium text-accent-soft-foreground">Suggested action</div>
            <div className="mt-0.5 text-base text-foreground">{suggestedAction}</div>
          </div>
        )}
      </div>

      {!decided && (onApprove || onReject || onEdit) && (
        <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
          {onApprove && (
            <Button size="sm" onClick={() => run('approve', onApprove)} loading={busy === 'approve'} disabled={!!busy}>
              {busy !== 'approve' && <Check />}
              Approve
            </Button>
          )}
          {onReject && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => run('reject', onReject)}
              loading={busy === 'reject'}
              disabled={!!busy}
            >
              {busy !== 'reject' && <X />}
              Reject
            </Button>
          )}
          {onEdit && (
            <Button size="sm" variant="ghost" onClick={onEdit} disabled={!!busy}>
              <Pencil />
              Edit
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}
