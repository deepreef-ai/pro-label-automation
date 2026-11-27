/**
 * Agents Center state. Findings + outbox are held in a module-level store so
 * decisions survive tab switches and navigation. In mock mode every decision is
 * applied in memory (fixtures never change); in live mode the server reply wins and the API is the truth.
 */
import { useSyncExternalStore } from 'react'
import type {
  AgentRunResponse,
  AgentsResponse,
  ApproveResult,
  Finding,
  FindingsResponse,
  OutboxItem,
  OutboxResponse,
} from '@contract/types'
import { api, isNoData } from '@/lib/api'
import { getRole } from '@/lib/role'

export interface AgentsState {
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string | null
  findings: Finding[]
  outbox: OutboxItem[]
  agents: AgentsResponse | null
  lastRunAt: string | null
  /** ids approved in this session (for the "moved to Done" highlight) */
  recentlyDone: string[]
}

let state: AgentsState = {
  status: 'idle',
  error: null,
  findings: [],
  outbox: [],
  agents: null,
  lastRunAt: null,
  recentlyDone: [],
}
const listeners = new Set<() => void>()

function set(patch: Partial<AgentsState>) {
  state = { ...state, ...patch }
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useAgentsState(): AgentsState {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  )
}

export const isMock = api.mode === 'mock'

/** Mock mode only: decisions are simulated in memory because the fixtures never change. */
function simulated(): boolean {
  return isMock
}

async function safeGet<T>(path: string, fallback: T): Promise<T> {
  try {
    return await api.get<T>(path)
  } catch (e) {
    if (isNoData(e)) return fallback
    throw e
  }
}

function nowIso(): string {
  return new Date().toISOString()
}

function maxIso(values: (string | null | undefined)[]): string | null {
  let best: string | null = null
  for (const v of values) if (v && (!best || Date.parse(v) > Date.parse(best))) best = v
  return best
}

function upsertFinding(f: Finding) {
  set({ findings: state.findings.map((x) => (x.id === f.id ? f : x)) })
}

function mergeOutbox(items: OutboxItem[]) {
  if (!items.length) return
  const byId = new Map(state.outbox.map((o) => [o.id, o]))
  for (const o of items) byId.set(o.id, o)
  set({ outbox: [...byId.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)) })
}

interface DraftMessage {
  channel?: string
  to?: string
  subject?: string
  body?: string
}

export function messagesOf(f: Finding): DraftMessage[] {
  const m = f.suggested_action.payload.messages
  return Array.isArray(m) ? (m as DraftMessage[]) : []
}

/** Mock: what the backend would put in the outbox when a finding is approved. */
function simulateOutbox(f: Finding): OutboxItem[] {
  const role = getRole()
  const at = nowIso()
  const nextId = (() => {
    let n = state.outbox.reduce((m, o) => Math.max(m, Number(o.id.replace(/\D/g, '')) || 0), 100)
    return () => `OB-${String(++n).padStart(4, '0')}`
  })()
  const base = { agent: f.agent, finding_id: f.id, status: 'sent' as const, approved_by: role, sent_at: at, simulated: true }

  if (f.suggested_action.type === 'draft_messages') {
    const existing = state.outbox.filter((o) => o.finding_id === f.id)
    return messagesOf(f).map((m) => {
      const match = existing.find((o) => m.to && o.to.startsWith(m.to))
      const channel = m.channel === 'email' ? 'email' : 'whatsapp'
      return {
        ...(match ?? { id: nextId(), created_at: at, subject: m.subject ?? 'Message' }),
        ...base,
        channel,
        to: match?.to ?? m.to ?? '—',
        subject: m.subject ?? match?.subject ?? 'Message',
        body: m.body ?? '',
      } as OutboxItem
    })
  }
  if (f.suggested_action.type === 'none') return []
  return [
    {
      id: nextId(),
      created_at: at,
      ...base,
      channel: 'task',
      to: String(f.suggested_action.payload.assign_to ?? 'owner'),
      subject: f.title,
      body: describeActionText(f),
    },
  ]
}

/** Plain-words summary of the suggested action (also used for task bodies). */
export function describeActionText(f: Finding): string {
  const p = f.suggested_action.payload as Record<string, unknown>
  const num = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('en-IN') : String(v ?? ''))
  switch (f.suggested_action.type) {
    case 'draft_messages': {
      const msgs = messagesOf(f)
      const ch = new Set(msgs.map((m) => (m.channel === 'email' ? 'email' : 'WhatsApp')))
      return `Send ${msgs.length} ${[...ch].join(' / ')} message${msgs.length === 1 ? '' : 's'} (drafts below; edit before approving).`
    }
    case 'draft_purchase_request':
      return `Raise a purchase request for ${num(p.suggested_qty_m ?? p.qty_m)} m of ${String(p.item_id ?? 'the item')} from ${String(
        p.vendor_id ?? 'the usual vendor',
      )}, needed by ${String(p.needed_by ?? 'soon')}.`
    case 'schedule_payment':
      return `Schedule ₹${num(p.amount)} to ${String(p.vendor_id ?? 'the supplier')} by ${String(p.mode ?? 'bank').toUpperCase()} on ${String(
        p.pay_on ?? 'the due date',
      )}.`
    case 'apply_fixes':
      return `Apply ${num(p.count)} automatic fixes (${String(p.kind ?? 'data').replace(/_/g, ' ')}).`
    case 'create_task':
      return `Task for ${String(p.assign_to ?? 'team')}: ${String(p.title ?? f.title)}${p.due ? ` (due ${String(p.due)})` : ''}.`
    case 'draft_journal': {
      const n = Array.isArray(p.entries) ? p.entries.length : 0
      return `Draft ${n} journal entr${n === 1 ? 'y' : 'ies'} for ${String(p.month ?? 'the month')} for accounts to post in Tally.`
    }
    case 'notify':
      return `Notify ${String(p.to ?? 'the team')}.`
    default:
      return 'No action needed: approve to mark as read.'
  }
}

export const agentsStore = {
  async load(force = false) {
    if (state.status === 'loading') return
    if (!force && state.status === 'ready' && simulated()) return
    set({ status: state.status === 'ready' ? 'ready' : 'loading', error: null })
    try {
      const [open, done, rejected, outbox, agents] = await Promise.all([
        safeGet<FindingsResponse>('/api/agents/findings?status=open', { status: 'open', items: [] }),
        safeGet<FindingsResponse>('/api/agents/findings?status=done', { status: 'done', items: [] }),
        safeGet<FindingsResponse>('/api/agents/findings?status=rejected', { status: 'rejected', items: [] }),
        safeGet<OutboxResponse>('/api/outbox', { items: [] }),
        safeGet<AgentsResponse | null>('/api/agents', null),
      ])
      const seen = new Set<string>()
      const findings = [...open.items, ...done.items, ...rejected.items].filter((f) => {
        if (seen.has(f.id)) return false
        seen.add(f.id)
        return true
      })
      set({
        status: 'ready',
        findings,
        outbox: [...outbox.items].sort((a, b) => b.created_at.localeCompare(a.created_at)),
        agents,
        lastRunAt: state.lastRunAt ?? maxIso(agents?.agents.map((a) => a.last_run_at) ?? []),
      })
    } catch (e) {
      set({ status: 'error', error: (e as Error).message })
    }
  },

  async runAll(): Promise<AgentRunResponse> {
    const res = await api.post<AgentRunResponse>('/api/agents/run', { agent: 'all' })
    const sim = simulated()
    const last = sim ? nowIso() : maxIso(res.runs.map((r) => r.finished_at ?? r.started_at))
    set({ lastRunAt: last ?? state.lastRunAt })
    if (!sim) await agentsStore.load(true)
    return res
  },

  async approve(f: Finding) {
    const res = await api.post<ApproveResult>(`/api/agents/findings/${f.id}/approve`)
    if (simulated()) {
      const updated: Finding = { ...f, status: 'done', decided_by: getRole(), decided_at: nowIso(), reason: null }
      mergeOutbox(simulateOutbox(f))
      upsertFinding(updated)
    } else {
      upsertFinding(res.finding)
      mergeOutbox(res.outbox ?? [])
    }
    set({ recentlyDone: [...state.recentlyDone, f.id] })
  },

  async reject(f: Finding, reason: string) {
    const res = await api.post<Finding>(`/api/agents/findings/${f.id}/reject`, { reason })
    upsertFinding(
      simulated() ? { ...f, status: 'rejected', decided_by: getRole(), decided_at: nowIso(), reason } : res,
    )
  },

  async edit(f: Finding, payload: Record<string, unknown>) {
    const res = await api.post<Finding>(`/api/agents/findings/${f.id}/edit`, { payload })
    const updated = simulated() ? { ...f, suggested_action: { ...f.suggested_action, payload } } : res
    upsertFinding(updated)
    if (simulated() && updated.suggested_action.type === 'draft_messages') {
      // Keep pending outbox drafts in sync with the edited text.
      const msgs = messagesOf(updated)
      set({
        outbox: state.outbox.map((o) => {
          if (o.finding_id !== f.id || o.status !== 'draft') return o
          const m = msgs.find((x) => x.to && o.to.startsWith(x.to))
          return m?.body ? { ...o, body: m.body } : o
        }),
      })
    }
    return updated
  },
}
