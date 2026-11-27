import { ArrowRight, Bot, Check, FileText, Link2, X } from 'lucide-react'
import { Badge, Button } from '@/components/ui'
import { cn } from '@/lib/utils'
import { draftBody, type ChatTurn, type DraftAction, type DraftState } from './types'

const ROUTE_NAMES: Record<string, string> = {
  '/': 'Dashboard',
  '/marketing': 'Marketing',
  '/jobs': 'Jobs',
  '/design': 'Design',
  '/store': 'Store',
  '/production': 'Production',
  '/qc': 'QC',
  '/dispatch': 'Dispatch',
  '/money': 'Money',
  '/agents': 'Agents Center',
  '/floor': 'Floor Board',
  '/settings': 'Settings',
}

export function routeLabel(to: string): string {
  const path = to.split(/[?#]/)[0]
  const job = /^\/jobs\/(JC-\d+)/i.exec(path)
  if (job) return job[1]
  const tab = /[?&]tab=([a-z-]+)/i.exec(to)?.[1]
  const base = ROUTE_NAMES[path] ?? path
  return tab ? `${base} · ${tab.replace(/-/g, ' ')}` : base
}

function prettyValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (Array.isArray(v)) return v.length > 4 ? `${v.length} entries` : v.map(String).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function DraftCard({
  draft,
  state,
  onConfirm,
  onCancel,
}: {
  draft: DraftAction
  state: DraftState
  onConfirm: () => void
  onCancel: () => void
}) {
  const body = draftBody(draft)
  const fields = Object.entries(body).filter(([k]) => k !== 'note' || !draft.text)
  return (
    <div className="mt-3 rounded-lg border border-border bg-surface p-3 shadow-xs">
      <div className="flex items-start gap-2">
        <FileText className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-foreground">Draft</span>
            {draft.entity && <Badge tone="info">{draft.entity.replace(/_/g, ' ')}</Badge>}
            {state === 'confirmed' && <Badge tone="ok">Saved</Badge>}
            {state === 'cancelled' && <Badge tone="neutral">Cancelled</Badge>}
          </div>
          <p className="mt-1 text-sm text-foreground">{draft.summary}</p>
        </div>
      </div>
      {draft.text && (
        <p className="mt-2 rounded-md bg-surface-muted p-2.5 text-sm whitespace-pre-wrap text-foreground">{draft.text}</p>
      )}
      {fields.length > 0 && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
          {fields.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k.replace(/_/g, ' ')}</dt>
              <dd className="truncate font-medium text-foreground" title={prettyValue(v)}>
                {prettyValue(v)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <p className="mt-2 font-mono text-[11px] text-muted-foreground">POST {draft.endpoint}</p>
      {(state === 'pending' || state === 'saving') && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={onConfirm} loading={state === 'saving'}>
            <Check /> Confirm
          </Button>
          <Button size="sm" variant="secondary" onClick={onCancel} disabled={state === 'saving'}>
            <X /> Cancel
          </Button>
        </div>
      )}
    </div>
  )
}

export function ChatMessage({
  turn,
  shownText,
  onNavigate,
  onDraft,
}: {
  turn: ChatTurn
  shownText: string
  onNavigate: (to: string) => void
  onDraft: (turnId: string, index: number, confirm: boolean) => void
}) {
  if (turn.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-accent px-3.5 py-2 text-sm whitespace-pre-wrap text-accent-foreground">
          {turn.content}
        </div>
      </div>
    )
  }
  const done = !turn.revealing
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-soft-foreground">
        <Bot className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div
          className={cn(
            'rounded-lg rounded-tl-sm border px-3.5 py-2 text-sm whitespace-pre-wrap',
            turn.error ? 'border-danger/40 bg-danger-soft text-danger-foreground' : 'border-border bg-surface-muted text-foreground',
          )}
        >
          {shownText}
          {!done && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-muted-foreground align-middle" />}
        </div>
        {done &&
          turn.actions?.map((a, i) =>
            a.type === 'navigate' ? (
              <Button key={i} size="sm" variant="secondary" className="mt-2 mr-2" onClick={() => onNavigate(a.to)}>
                Open {routeLabel(a.to)} <ArrowRight />
              </Button>
            ) : (
              <DraftCard
                key={i}
                draft={a}
                state={turn.drafts?.[i] ?? 'pending'}
                onConfirm={() => onDraft(turn.id, i, true)}
                onCancel={() => onDraft(turn.id, i, false)}
              />
            ),
          )}
        {done && turn.sources && turn.sources.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>Sources:</span>
            {turn.sources.map((s, i) =>
              s.link ? (
                <button
                  key={i}
                  type="button"
                  onClick={() => onNavigate(s.link!)}
                  className="inline-flex items-center gap-1 rounded-sm border border-border px-1.5 py-0.5 hover:border-border-strong hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <Link2 className="size-3" aria-hidden />
                  {s.label}
                </button>
              ) : (
                <span key={i} className="rounded-sm border border-border px-1.5 py-0.5">
                  {s.label}
                </span>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  )
}
