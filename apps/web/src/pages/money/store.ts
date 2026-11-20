/**
 * In-memory overlay for Money mutations in mock mode.
 * Fixtures never change, so releases / follow-ups / payments / drafted invoices
 * are kept here for the session and applied on top of fixture data.
 * In live mode the backend is the truth and screens simply refetch.
 */
import { useSyncExternalStore } from 'react'
import type { Collection, Creditors, Debtors, Invoice, Payment, ReleaseLockResult } from '@contract/types'
import { api } from '@/lib/api'

interface MoneyOverlay {
  releases: Record<string, ReleaseLockResult>
  collections: Collection[]
  invoices: Invoice[]
  payments: Payment[]
}

let state: MoneyOverlay = { releases: {}, collections: [], invoices: [], payments: [] }
const listeners = new Set<() => void>()

function emit(next: MoneyOverlay) {
  state = next
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useMoneyOverlay(): MoneyOverlay {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  )
}

export const isMock = api.mode === 'mock'

export const moneyStore = {
  release(r: ReleaseLockResult) {
    emit({ ...state, releases: { ...state.releases, [r.client_id]: r } })
  },
  addCollection(c: Collection) {
    emit({ ...state, collections: [c, ...state.collections] })
  },
  addInvoice(i: Invoice) {
    emit({ ...state, invoices: [i, ...state.invoices.filter((x) => x.id !== i.id)] })
  },
  addPayment(p: Payment) {
    emit({ ...state, payments: [...state.payments, p] })
  },
}

/* ------------------------------------------------------------------ */
/* Overlay appliers (no-ops in live mode)                              */
/* ------------------------------------------------------------------ */

export function applyDebtors(d: Debtors, o: MoneyOverlay): Debtors {
  if (!isMock || Object.keys(o.releases).length === 0) return d
  let locked = d.totals.locked
  const clients = d.clients.map((c) => {
    const r = o.releases[c.client_id]
    if (!r || c.lock_status !== 'locked') return c
    locked -= c.outstanding
    return { ...c, lock_status: 'ok' as const, locked_since: null, locks_on: r.valid_until }
  })
  return { ...d, clients, totals: { ...d.totals, locked: Math.max(0, locked) } }
}

export function applyInvoices(items: Invoice[], o: MoneyOverlay): Invoice[] {
  if (!isMock || o.invoices.length === 0) return items
  const ids = new Set(o.invoices.map((i) => i.id))
  return [...o.invoices, ...items.filter((i) => !ids.has(i.id))]
}

export function applyCollections(items: Collection[], o: MoneyOverlay): Collection[] {
  if (!isMock || o.collections.length === 0) return items
  return [...o.collections, ...items]
}

export function applyCreditors(c: Creditors, o: MoneyOverlay): Creditors {
  if (!isMock || o.payments.length === 0) return c
  const balances = new Map<string, number>()
  for (const p of o.payments) for (const a of p.allocations) balances.set(a.bill_id, a.balance_after)
  let paidTotal = 0
  let msmeDue = c.totals.msme_due_7d
  let due7 = c.totals.due_7d
  let overdue = c.totals.overdue
  const vendors = c.vendors.map((v) => {
    let outstanding = 0
    const bills = v.bills.map((b) => {
      const after = balances.get(b.id)
      if (after === undefined) {
        outstanding += b.balance
        return b
      }
      const cleared = b.balance - after
      paidTotal += cleared
      if (b.days_to_due < 0) overdue -= cleared
      else if (b.days_to_due <= 7) {
        due7 -= cleared
        if (v.msme) msmeDue -= cleared
      }
      outstanding += after
      return {
        ...b,
        paid: b.amount - after,
        balance: after,
        status: after <= 0.005 ? ('paid' as const) : ('part_paid' as const),
      }
    })
    const open = bills.filter((b) => b.balance > 0.005).sort((a, b) => a.due_date.localeCompare(b.due_date))
    return { ...v, bills, outstanding, next_due_date: open[0]?.due_date ?? null }
  })
  return {
    ...c,
    vendors,
    totals: {
      outstanding: Math.max(0, c.totals.outstanding - paidTotal),
      overdue: Math.max(0, overdue),
      due_7d: Math.max(0, due7),
      msme_due_7d: Math.max(0, msmeDue),
    },
  }
}

export function todayISO(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
