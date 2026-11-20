import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Bot, CheckCircle2, Inbox, Play, Send } from 'lucide-react'
import type { Finding } from '@contract/types'
import {
  ApprovalCard,
  Badge,
  Button,
  DataTable,
  EmptyState,
  PageHeader,
  PageSkeleton,
  Sheet,
  SheetTrigger,
  StatusChip,
  Tabs,
  TabsList,
  TabsTrigger,
  toast,
  type Column,
} from '@/components/ui'
import { formatDateTime, formatRelative } from '@/lib/format'
import { ROLE_LABELS, type Role } from '@/lib/role'
import { cn } from '@/lib/utils'
import { EditFindingDialog, RejectDialog } from './edit-dialog'
import { OutboxSheet } from './outbox'
import { agentsStore, describeActionText, messagesOf, useAgentsState } from './store'

type TabKey = 'all' | 'store' | 'production' | 'money' | 'planning' | 'done' | 'rejected' | 'history'

const GROUP: Record<string, Exclude<TabKey, 'all' | 'done' | 'rejected' | 'history'> | undefined> = {
  import_checker: 'store',
  store_watchdog: 'store',
  wastage_watchdog: 'production',
  planning: 'planning',
  collections: 'money',
  payables: 'money',
  month_end: 'money',
}

const TABS: { value: TabKey; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'store', label: 'Store' },
  { value: 'production', label: 'Production' },
  { value: 'money', label: 'Money' },
  { value: 'planning', label: 'Planning' },
  { value: 'done', label: 'Done' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'history', label: 'History' },
]

const SEV_ORDER = { high: 0, medium: 1, low: 2 }

function humanize(name: string) {
  return name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function personLabel(by: string | null) {
  if (!by) return '—'
  return ROLE_LABELS[by as Role] ?? by
}

function SuggestedAction({ f }: { f: Finding }) {
  const msgs = messagesOf(f)
  return (
    <div className="space-y-2">
      <p>{describeActionText(f)}</p>
      {msgs.length > 0 && (
        <ul className="space-y-1.5">
          {msgs.slice(0, 2).map((m, i) => (
            <li key={i} className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm">
              <span className="font-medium text-foreground">{m.to}: </span>
              <span className="text-muted-foreground">{m.body}</span>
            </li>
          ))}
          {msgs.length > 2 && <li className="text-xs text-muted-foreground">+ {msgs.length - 2} more</li>}
        </ul>
      )}
    </div>
  )
}

export default function AgentsPage() {
  const s = useAgentsState()
  const [tab, setTab] = useState<TabKey>('all')
  const [running, setRunning] = useState(false)
  const [editing, setEditing] = useState<Finding | null>(null)
  const [rejecting, setRejecting] = useState<Finding | null>(null)
  const [doneFlash, setDoneFlash] = useState(false)

  useEffect(() => {
    void agentsStore.load()
  }, [])

  const labels = useMemo(() => {
    const m: Record<string, string> = {}
    for (const a of s.agents?.agents ?? []) m[a.name] = a.label
    return m
  }, [s.agents])
  const agentLabel = (name: string) => labels[name] ?? humanize(name)

  const open = useMemo(
    () =>
      s.findings
        .filter((f) => f.status === 'open')
        .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || b.created_at.localeCompare(a.created_at)),
    [s.findings],
  )
  const decided = useMemo(
    () =>
      s.findings
        .filter((f) => f.status !== 'open')
        .sort((a, b) => (b.decided_at ?? '').localeCompare(a.decided_at ?? '')),
    [s.findings],
  )
  const count = (t: TabKey) => {
    if (t === 'all') return open.length
    if (t === 'done') return decided.filter((f) => f.status === 'done').length
    if (t === 'rejected') return decided.filter((f) => f.status === 'rejected').length
    if (t === 'history') return decided.length
    return open.filter((f) => GROUP[f.agent] === t).length
  }

  const visible =
    tab === 'all'
      ? open
      : tab === 'done' || tab === 'rejected'
        ? decided.filter((f) => f.status === tab)
        : open.filter((f) => GROUP[f.agent] === tab)

  const runAll = async () => {
    setRunning(true)
    try {
      const res = await agentsStore.runAll()
      const created = res.runs.reduce((n, r) => n + r.findings_created, 0)
      const failed = res.runs.filter((r) => r.status === 'failed').length
      toast.success(`${res.runs.length} agents ran`, {
        description: `${created} new finding${created === 1 ? '' : 's'}${failed ? `, ${failed} failed` : ''}.`,
      })
    } catch (e) {
      toast.error('Could not run the agents', { description: (e as Error).message })
    } finally {
      setRunning(false)
    }
  }

  const approve = async (f: Finding) => {
    try {
      await agentsStore.approve(f)
      setDoneFlash(true)
      window.setTimeout(() => setDoneFlash(false), 1600)
      const msgs = messagesOf(f).length
      toast.success('Approved', {
        description: msgs ? `${msgs} message${msgs === 1 ? '' : 's'} sent to the Outbox (simulated).` : 'Moved to Done.',
      })
    } catch (e) {
      toast.error('Could not approve', { description: (e as Error).message })
    }
  }

  const historyCols: Column<Finding>[] = [
    {
      key: 'title',
      header: 'Finding',
      cell: (f) => (
        <div className="min-w-56">
          <div className="font-medium">{f.title}</div>
          <div className="text-xs text-muted-foreground">
            {f.id} · {agentLabel(f.agent)}
          </div>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Decision',
      cell: (f) => <StatusChip tone={f.status === 'done' ? 'ok' : 'neutral'}>{f.status === 'done' ? 'Approved' : 'Rejected'}</StatusChip>,
    },
    { key: 'decided_by', header: 'Decided by', cell: (f) => personLabel(f.decided_by) },
    {
      key: 'decided_at',
      header: 'When',
      cell: (f) => <span className="whitespace-nowrap">{formatDateTime(f.decided_at)}</span>,
    },
    {
      key: 'reason',
      header: 'Reason',
      sortable: false,
      cell: (f) => <span className="text-sm text-muted-foreground">{f.reason ?? '—'}</span>,
    },
  ]

  const pendingOutbox = s.outbox.filter((o) => o.status === 'draft').length

  return (
    <div>
      <PageHeader
        title="Agents Center"
        subtitle="Eight agents watch store, production, planning and money. They only draft: nothing happens until you approve."
        meta={
          s.lastRunAt ? (
            <span className="text-sm text-muted-foreground" title={formatDateTime(s.lastRunAt)}>
              Last run {formatRelative(s.lastRunAt)}
            </span>
          ) : undefined
        }
        actions={
          <>
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="secondary">
                  <Send />
                  Outbox
                  {s.outbox.length > 0 && (
                    <Badge size="sm" tone={pendingOutbox ? 'warn' : 'neutral'}>
                      {s.outbox.length}
                    </Badge>
                  )}
                </Button>
              </SheetTrigger>
              <OutboxSheet items={s.outbox} />
            </Sheet>
            <Button onClick={runAll} loading={running}>
              {!running && <Play />}
              Run all agents now
            </Button>
          </>
        }
      />

      {s.status === 'error' ? (
        <EmptyState
          icon={AlertTriangle}
          title="Couldn't load findings"
          description={s.error ?? undefined}
          action={
            <Button variant="secondary" size="sm" onClick={() => agentsStore.load(true)}>
              Try again
            </Button>
          }
        />
      ) : s.status !== 'ready' ? (
        <PageSkeleton />
      ) : (
        <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
          <TabsList aria-label="Filter findings">
            {TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
                <span
                  className={cn(
                    'tabular rounded-full bg-surface-muted px-1.5 text-xs text-muted-foreground transition-colors duration-300',
                    t.value === 'done' && doneFlash && 'bg-ok-soft text-ok-foreground',
                  )}
                >
                  {count(t.value)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          <div className="pt-5">
            {tab === 'history' ? (
              <DataTable
                columns={historyCols}
                rows={decided}
                rowKey={(f) => f.id}
                empty={<EmptyState compact title="No decisions yet" description="Approved and rejected findings appear here." />}
              />
            ) : visible.length === 0 ? (
              <EmptyState
                icon={tab === 'done' || tab === 'rejected' ? Inbox : CheckCircle2}
                title={tab === 'done' ? 'Nothing approved yet' : tab === 'rejected' ? 'Nothing rejected' : 'All clear'}
                description={
                  tab === 'done' || tab === 'rejected'
                    ? 'Decisions show up here.'
                    : 'No open findings here. Run the agents to check again.'
                }
              />
            ) : (
              <motion.div layout className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <AnimatePresence mode="popLayout" initial={false}>
                  {visible.map((f) => (
                    <motion.div
                      key={f.id}
                      layout
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, x: 60, scale: 0.97, transition: { duration: 0.28 } }}
                      transition={{ type: 'spring', stiffness: 380, damping: 34 }}
                      className={cn(
                        'h-full rounded-lg',
                        tab === 'done' && s.recentlyDone.includes(f.id) && 'ring-2 ring-ok/40',
                      )}
                    >
                      <ApprovalCard
                        className="h-full"
                        who={
                          <span className="inline-flex items-center gap-1.5">
                            <Bot className="size-3.5 text-muted-foreground" aria-hidden />
                            {agentLabel(f.agent)}
                          </span>
                        }
                        createdAt={f.created_at}
                        severity={f.severity}
                        status={f.status}
                        what={f.title}
                        detail={
                          <>
                            <p>{f.detail}</p>
                            {f.status !== 'open' && (
                              <p className="mt-2 text-xs text-subtle-foreground">
                                {f.status === 'done' ? 'Approved' : 'Rejected'} by {personLabel(f.decided_by)} ·{' '}
                                {formatDateTime(f.decided_at)}
                                {f.reason ? ` · “${f.reason}”` : ''}
                              </p>
                            )}
                          </>
                        }
                        evidence={f.evidence}
                        suggestedAction={<SuggestedAction f={f} />}
                        onApprove={() => approve(f)}
                        onReject={() => setRejecting(f)}
                        onEdit={f.suggested_action.type !== 'none' ? () => setEditing(f) : undefined}
                      />
                    </motion.div>
                  ))}
                </AnimatePresence>
              </motion.div>
            )}
          </div>
        </Tabs>
      )}

      <EditFindingDialog finding={editing} onClose={() => setEditing(null)} />
      <RejectDialog finding={rejecting} onClose={() => setRejecting(null)} />
    </div>
  )
}
