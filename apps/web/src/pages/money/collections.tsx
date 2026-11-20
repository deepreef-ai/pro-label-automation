import { useMemo, useState } from 'react'
import { MessageSquarePlus } from 'lucide-react'
import type { Collection, CollectionCreate, Debtors } from '@contract/types'
import {
  Button,
  DataTable,
  DemoBadge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  Input,
  QueryState,
  Segmented,
  Select,
  StatusChip,
  Textarea,
  toast,
  type Column,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatDate, formatDateShort, formatINR, formatINRShort } from '@/lib/format'
import { ROLE_LABELS, useRole } from '@/lib/role'
import { Stat } from './shared'
import { applyCollections, isMock, moneyStore, todayISO, useMoneyOverlay } from './store'

const MODE_LABEL: Record<Collection['mode'], string> = {
  call: 'Call',
  whatsapp: 'WhatsApp',
  email: 'Email',
  visit: 'Visit',
}

type Filter = 'all' | 'open' | 'kept' | 'broken'

/** Contract has no "received" field: a kept promise counts as received in full. */
function receivedOf(c: Collection): number | null {
  if (c.status === 'kept') return c.promise_amount ?? 0
  if (c.status === 'broken') return 0
  return null
}

function statusChip(c: Collection) {
  if (c.status === 'kept') return <StatusChip tone="ok">Kept</StatusChip>
  if (c.status === 'broken') return <StatusChip tone="danger">Broken</StatusChip>
  return <StatusChip tone="neutral">{c.promise_date ? 'Awaiting' : 'Follow-up'}</StatusChip>
}

export function CollectionsTab() {
  const overlay = useMoneyOverlay()
  const q = useApi<Collection[]>('/api/collections')
  const [filter, setFilter] = useState<Filter>('all')
  const [open, setOpen] = useState(false)

  const columns: Column<Collection>[] = useMemo(
    () => [
      { key: 'date', header: 'Date', cell: (r) => <span className="whitespace-nowrap">{formatDate(r.date)}</span> },
      {
        key: 'client_name',
        header: 'Client',
        cell: (r) => (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 font-medium">
              {r.client_name}
              <DemoBadge show={r.is_demo} />
            </div>
            <div className="text-xs text-muted-foreground">
              {MODE_LABEL[r.mode]}
              {r.contact ? ` · ${r.contact}` : ''}
            </div>
          </div>
        ),
      },
      { key: 'by', header: 'Collector' },
      {
        key: 'promise_amount',
        header: 'Promise',
        align: 'right',
        cell: (r) =>
          r.promise_amount != null ? (
            <div className="whitespace-nowrap">
              {formatINRShort(r.promise_amount)}
              <div className="text-xs text-muted-foreground">by {formatDateShort(r.promise_date)}</div>
            </div>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        key: 'received',
        header: 'Received',
        align: 'right',
        sortValue: (r) => receivedOf(r),
        cell: (r) => {
          const v = receivedOf(r)
          return v == null ? <span className="text-muted-foreground">—</span> : formatINRShort(v)
        },
      },
      { key: 'status', header: 'Result', cell: statusChip },
      {
        key: 'note',
        header: 'Note',
        sortable: false,
        cell: (r) => <span className="line-clamp-2 min-w-48 text-sm text-muted-foreground">{r.note}</span>,
      },
      {
        key: 'next_follow_up',
        header: 'Next follow-up',
        cell: (r) => <span className="whitespace-nowrap">{formatDateShort(r.next_follow_up)}</span>,
      },
    ],
    [],
  )

  return (
    <QueryState query={q}>
      {(raw) => {
        const all = applyCollections(raw, overlay)
        const rows = filter === 'all' ? all : all.filter((c) => c.status === filter)
        const promised = all.filter((c) => c.status === 'open').reduce((s, c) => s + (c.promise_amount ?? 0), 0)
        const kept = all.filter((c) => c.status === 'kept').length
        const broken = all.filter((c) => c.status === 'broken').length
        return (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 rounded-lg border border-border bg-surface p-5 sm:grid-cols-4">
              <Stat label="Follow-ups logged" value={all.length} />
              <Stat label="Promised, awaiting" value={formatINRShort(promised)} />
              <Stat label="Promises kept" value={kept} tone="ok" />
              <Stat label="Promises broken" value={broken} tone={broken ? 'danger' : undefined} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Segmented<Filter>
                aria-label="Filter follow-ups"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'open', label: 'Awaiting' },
                  { value: 'kept', label: 'Kept' },
                  { value: 'broken', label: 'Broken' },
                ]}
              />
              <Button onClick={() => setOpen(true)}>
                <MessageSquarePlus />
                Log follow-up
              </Button>
            </div>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.id}
              defaultSort={{ key: 'date', dir: 'desc' }}
              empty={<EmptyState compact title="No follow-ups here" description="Log a call, visit or message." />}
            />
            <LogDialog
              open={open}
              onOpenChange={setOpen}
              onSaved={(c) => {
                if (isMock) moneyStore.addCollection(c)
                else q.refetch()
              }}
            />
          </div>
        )
      }}
    </QueryState>
  )
}

function LogDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onSaved: (c: Collection) => void
}) {
  const role = useRole()
  const dq = useApi<Debtors>(open ? '/api/debtors' : null)
  const [clientId, setClientId] = useState('')
  const [mode, setMode] = useState<Collection['mode']>('call')
  const [contact, setContact] = useState('')
  const [note, setNote] = useState('')
  const [promiseDate, setPromiseDate] = useState('')
  const [promiseAmount, setPromiseAmount] = useState('')
  const [nextFollowUp, setNextFollowUp] = useState('')
  const [busy, setBusy] = useState(false)

  const client = dq.data?.clients.find((c) => c.client_id === clientId)
  const amount = promiseAmount ? Number(promiseAmount) : null
  const valid = !!clientId && note.trim().length > 0 && (amount === null || (Number.isFinite(amount) && amount > 0))

  const reset = () => {
    setClientId('')
    setMode('call')
    setContact('')
    setNote('')
    setPromiseDate('')
    setPromiseAmount('')
    setNextFollowUp('')
  }

  const submit = async () => {
    if (!valid || !client) return
    setBusy(true)
    const body: CollectionCreate = {
      date: todayISO(),
      client_id: clientId,
      mode,
      contact: contact.trim() || undefined,
      note: note.trim(),
      promise_date: promiseDate || null,
      promise_amount: amount,
      next_follow_up: nextFollowUp || promiseDate || null,
    }
    try {
      const res = await api.post<Collection>('/api/collections', body)
      const row: Collection = isMock
        ? {
            ...res,
            id: `COL-${String(Date.now()).slice(-4)}`,
            date: body.date,
            client_id: clientId,
            client_name: client.client_name,
            invoice_ids: [],
            mode,
            contact: body.contact ?? '',
            note: body.note,
            promise_date: body.promise_date ?? null,
            promise_amount: body.promise_amount ?? null,
            status: 'open',
            next_follow_up: body.next_follow_up ?? null,
            by: ROLE_LABELS[role],
          }
        : res
      onSaved(row)
      toast.success(`Follow-up logged for ${client.client_name}`, {
        description: row.promise_amount
          ? `Promise ${formatINR(row.promise_amount)} by ${formatDate(row.promise_date)}`
          : undefined,
      })
      reset()
      onOpenChange(false)
    } catch (e) {
      toast.error('Could not save the follow-up', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Log follow-up</DialogTitle>
          <DialogDescription>Record a call, message or visit and any payment promise the client made.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Client"
            htmlFor="col-client"
            hint={client ? `${formatINR(client.outstanding)} outstanding` : undefined}
            className="sm:col-span-2"
          >
            <Select
              id="col-client"
              value={clientId}
              onValueChange={setClientId}
              placeholder={dq.loading ? 'Loading clients…' : 'Choose a client'}
              options={(dq.data?.clients ?? []).map((c) => ({
                value: c.client_id,
                label: `${c.client_name} · ${formatINRShort(c.outstanding)}`,
              }))}
            />
          </Field>
          <Field label="How" htmlFor="col-mode">
            <Select
              id="col-mode"
              value={mode}
              onValueChange={(v) => setMode(v as Collection['mode'])}
              options={Object.entries(MODE_LABEL).map(([value, label]) => ({ value, label }))}
            />
          </Field>
          <Field label="Spoke to" htmlFor="col-contact">
            <Input id="col-contact" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Contact name" />
          </Field>
          <Field label="Note" htmlFor="col-note" className="sm:col-span-2">
            <Textarea id="col-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did they say?" />
          </Field>
          <Field label="Promised amount (₹)" htmlFor="col-amt">
            <Input
              id="col-amt"
              type="number"
              inputMode="decimal"
              min={0}
              value={promiseAmount}
              onChange={(e) => setPromiseAmount(e.target.value)}
              placeholder="Optional"
            />
          </Field>
          <Field label="Promised date" htmlFor="col-pdate">
            <Input id="col-pdate" type="date" value={promiseDate} onChange={(e) => setPromiseDate(e.target.value)} />
          </Field>
          <Field label="Next follow-up" htmlFor="col-next" hint="Defaults to the promised date">
            <Input id="col-next" type="date" value={nextFollowUp} onChange={(e) => setNextFollowUp(e.target.value)} />
          </Field>
        </div>
        {client && promiseDate && client.locks_on && client.lock_status === 'at_risk' && promiseDate > client.locks_on && (
          <p className="rounded-md bg-warn-soft px-3 py-2 text-sm text-warn-foreground">
            This promise is after the lock date ({formatDate(client.locks_on)}). The client will lock before the money arrives.
          </p>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy} disabled={!valid}>
            Save follow-up
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
