import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { FilePlus2, Sparkles, Truck } from 'lucide-react'
import type { Dispatch, Invoice, InvoiceListResponse } from '@contract/types'
import {
  Badge,
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
  QueryState,
  Segmented,
  StatusChip,
  toast,
  type Column,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { applyInvoices, isMock, moneyStore, useMoneyOverlay } from './store'

type Filter = 'all' | 'overdue' | 'not_due' | 'paid' | 'draft'

function invoiceState(i: Invoice): { label: string; tone: 'ok' | 'warn' | 'danger' | 'neutral' | 'info' } {
  if (i.status === 'draft') return { label: 'Draft', tone: 'info' }
  if (i.status === 'paid' || i.outstanding <= 0.005) return { label: 'Paid', tone: 'ok' }
  if (i.days_past_due > 0) return { label: 'Overdue', tone: 'danger' }
  return { label: 'Not due', tone: 'neutral' }
}

function filterOf(i: Invoice): Filter {
  const s = invoiceState(i).label
  return s === 'Paid' ? 'paid' : s === 'Overdue' ? 'overdue' : s === 'Draft' ? 'draft' : 'not_due'
}

export function InvoicesTab() {
  const overlay = useMoneyOverlay()
  const q = useApi<InvoiceListResponse>('/api/invoices')
  const [filter, setFilter] = useState<Filter>('all')
  const [draftOpen, setDraftOpen] = useState(false)

  const columns: Column<Invoice>[] = useMemo(
    () => [
      {
        key: 'id',
        header: 'Invoice',
        cell: (r) => (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium">{r.id}</span>
            {r.dispatch_id && (
              <Badge tone="accent" size="sm" title={`Drafted automatically from ${r.dispatch_id}`}>
                <Sparkles className="size-3" aria-hidden />
                Auto-drafted
              </Badge>
            )}
            <DemoBadge show={r.is_demo} />
          </div>
        ),
      },
      { key: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
      { key: 'client_name', header: 'Client', cell: (r) => <span className="whitespace-nowrap">{r.client_name}</span> },
      {
        key: 'job_card',
        header: 'Job',
        cell: (r) => (
          <Link to={`/jobs/${r.job_card}`} className="text-accent hover:underline">
            {r.job_card}
          </Link>
        ),
      },
      { key: 'taxable', header: 'Taxable', align: 'right', cell: (r) => formatINR(r.taxable) },
      { key: 'total', header: 'Total (incl. GST)', align: 'right', cell: (r) => formatINR(r.total) },
      {
        key: 'outstanding',
        header: 'Outstanding',
        align: 'right',
        cell: (r) => (
          <span className={cn(r.outstanding > 0 && r.days_past_due > 0 && 'font-medium text-danger-foreground')}>
            {formatINR(r.outstanding)}
          </span>
        ),
      },
      {
        key: 'due_date',
        header: 'Due',
        cell: (r) => (
          <div className="whitespace-nowrap">
            {formatDate(r.due_date)}
            {r.days_past_due > 0 && r.outstanding > 0 && (
              <div className="tabular text-xs text-danger-foreground">{r.days_past_due} days late</div>
            )}
          </div>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        sortValue: (r) => invoiceState(r).label,
        cell: (r) => {
          const s = invoiceState(r)
          return (
            <StatusChip tone={s.tone}>
              {s.label}
              {r.status === 'part_paid' ? ' · part paid' : ''}
            </StatusChip>
          )
        },
      },
    ],
    [],
  )

  return (
    <QueryState query={q}>
      {(data) => {
        const all = applyInvoices(data.items, overlay)
        const rows = filter === 'all' ? all : all.filter((i) => filterOf(i) === filter)
        const count = (f: Filter) => all.filter((i) => filterOf(i) === f).length
        const outstanding = all.reduce((s, i) => s + i.outstanding, 0)
        const overdueAmt = all.filter((i) => filterOf(i) === 'overdue').reduce((s, i) => s + i.outstanding, 0)
        return (
          <div className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm text-muted-foreground">
                <span>
                  Outstanding <strong className="tabular text-foreground">{formatINRShort(outstanding)}</strong>
                </span>
                <span>
                  Overdue <strong className="tabular text-danger-foreground">{formatINRShort(overdueAmt)}</strong>
                </span>
                <span>{all.length} invoices</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Segmented<Filter>
                  aria-label="Filter invoices"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'all', label: `All ${all.length}` },
                    { value: 'overdue', label: `Overdue ${count('overdue')}` },
                    { value: 'not_due', label: `Not due ${count('not_due')}` },
                    { value: 'paid', label: `Paid ${count('paid')}` },
                  ]}
                />
                <Button onClick={() => setDraftOpen(true)}>
                  <FilePlus2 />
                  Draft from dispatch
                </Button>
              </div>
            </div>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.id}
              defaultSort={{ key: 'date', dir: 'desc' }}
              empty={<EmptyState compact title="No invoices here" description="Try another filter." />}
            />
            <DraftDialog
              open={draftOpen}
              onOpenChange={setDraftOpen}
              invoicedDispatches={new Set(all.map((i) => i.dispatch_id).filter(Boolean) as string[])}
              onDrafted={(inv) => {
                if (isMock) moneyStore.addInvoice(inv)
                else q.refetch()
              }}
            />
          </div>
        )
      }}
    </QueryState>
  )
}

function DraftDialog({
  open,
  onOpenChange,
  invoicedDispatches,
  onDrafted,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  invoicedDispatches: Set<string>
  onDrafted: (inv: Invoice) => void
}) {
  const dq = useApi<Dispatch[]>(open ? '/api/dispatch' : null)
  const [busy, setBusy] = useState<string | null>(null)
  const pending = (dq.data ?? []).filter((d) => !d.invoice_id && !invoicedDispatches.has(d.id))

  const draft = async (d: Dispatch) => {
    setBusy(d.id)
    try {
      const inv = await api.post<Invoice>(`/api/invoices/draft-from-dispatch/${d.id}`)
      // Mock fixture is a single sample; make it match the chosen dispatch.
      const result: Invoice = isMock
        ? { ...inv, dispatch_id: d.id, job_card: d.job_card, client_id: d.client_id, client_name: d.client_name }
        : inv
      onDrafted(result)
      toast.success(`${result.id} drafted from ${d.id}`, {
        description: `${result.client_name} · ${formatINR(result.total)} incl. GST · due ${formatDate(result.due_date)}`,
      })
      onOpenChange(false)
    } catch (e) {
      toast.error('Could not draft the invoice', { description: (e as Error).message })
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Draft invoice from dispatch</DialogTitle>
          <DialogDescription>
            Quantity and rate come from the challan and job card. GST is added and the due date follows the client’s
            credit days. You can review the draft before it goes to Tally.
          </DialogDescription>
        </DialogHeader>
        {dq.loading && !dq.data ? (
          <div className="py-6 text-center text-sm text-muted-foreground">Loading dispatches…</div>
        ) : dq.error && !dq.noData ? (
          <EmptyState compact title="Couldn't load dispatches" description={dq.error.message} />
        ) : pending.length === 0 ? (
          <EmptyState compact icon={Truck} title="Nothing to invoice" description="Every dispatch already has an invoice." />
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {pending.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 font-medium text-foreground">
                    {d.id} <span className="text-muted-foreground">·</span> {d.job_card}
                    <DemoBadge show={d.is_demo} />
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {d.client_name} · {formatNumber(d.qty)} labels · {formatDate(d.date)}
                  </div>
                </div>
                <Button size="sm" onClick={() => draft(d)} loading={busy === d.id} disabled={!!busy}>
                  Draft invoice
                </Button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
