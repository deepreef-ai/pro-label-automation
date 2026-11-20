import { useMemo, useState } from 'react'
import { FileText, Printer, Truck } from 'lucide-react'
import type { Dispatch, DispatchCreate, Job, JobListResponse } from '@contract/types'
import { API_URL, api, ApiError, useApi } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Button,
  type Column,
  DataTable,
  DemoBadge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  KpiCard,
  PageHeader,
  QueryState,
  Select,
  StatusChip,
  TableSkeleton,
  toast,
} from '@/components/ui'
import { describeError, InlineAlert, todayIso, withAdded } from '@/pages/store/common'

const TRANSPORTERS = ['Metro Freight Carriers', 'Shree Logistics', 'VRL Logistics', 'Own vehicle', 'Client pickup']

export default function DispatchPage() {
  const q = useApi<Dispatch[]>('/api/dispatch')
  const jobsQ = useApi<JobListResponse>('/api/jobs')
  const [added, setAdded] = useState<Dispatch[]>([])
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<Dispatch | null>(null)

  const rows = useMemo(() => withAdded(added, q.data ?? []), [added, q.data])

  const openChallan = (d: Dispatch) => {
    if (api.mode === 'mock') setPreview(d)
    else window.open(`${API_URL}/api/dispatch/${encodeURIComponent(d.id)}/challan.pdf`, '_blank', 'noopener')
  }

  const columns: Column<Dispatch>[] = [
    {
      key: 'id',
      header: 'Challan',
      cell: (r) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {r.id} <DemoBadge show={r.is_demo} />
        </span>
      ),
    },
    { key: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    {
      key: 'job_card',
      header: 'Job / client',
      cell: (r) => (
        <div>
          <p className="font-medium">{r.job_card}</p>
          <p className="text-xs text-muted-foreground">{r.client_name}</p>
        </div>
      ),
    },
    {
      key: 'qty',
      header: 'Qty',
      align: 'right',
      cell: (r) => (
        <div>
          <p className="font-medium">{formatNumber(r.qty)}</p>
          <p className="text-xs text-muted-foreground">{r.boxes} boxes</p>
        </div>
      ),
    },
    {
      key: 'balance_after',
      header: 'QC balance',
      align: 'right',
      cell: (r) => (
        <div>
          <p>{formatNumber(r.balance_after)}</p>
          <p className="text-xs text-muted-foreground">of {formatNumber(r.qc_approved)} approved</p>
        </div>
      ),
    },
    {
      key: 'transporter',
      header: 'Transporter / LR',
      cell: (r) => (
        <div>
          <p>{r.transporter}</p>
          <p className="text-xs text-muted-foreground">
            {r.vehicle_no} · LR {r.lr_no || '—'}
          </p>
        </div>
      ),
    },
    { key: 'freight', header: 'Freight', align: 'right', cell: (r) => formatINR(r.freight) },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => (
        <StatusChip size="sm" tone={r.status === 'invoiced' ? 'info' : 'ok'}>
          {r.status === 'invoiced' ? `Invoiced ${r.invoice_id ?? ''}` : 'Dispatched'}
        </StatusChip>
      ),
    },
    {
      key: 'challan',
      header: '',
      sortable: false,
      cell: (r) => (
        <Button variant="ghost" size="sm" onClick={() => openChallan(r)} aria-label={`Open challan ${r.id}`}>
          <FileText aria-hidden /> Challan
        </Button>
      ),
    },
  ]

  const month = rows.filter((r) => r.date.slice(0, 7) === todayIso().slice(0, 7))
  const toInvoice = rows.filter((r) => r.status === 'dispatched')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dispatch"
        subtitle="Delivery challans against QC-approved quantity, with transporter, LR and freight."
        actions={
          <Button onClick={() => setOpen(true)}>
            <Truck aria-hidden /> New dispatch
          </Button>
        }
      />
      <QueryState query={q} loading={<TableSkeleton />}>
        {() => (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <KpiCard label="Labels dispatched this month" value={formatNumber(month.reduce((a, r) => a + r.qty, 0))} deltaLabel={`${month.length} challans`} />
              <KpiCard label="Freight this month" value={month.reduce((a, r) => a + r.freight, 0)} />
              <KpiCard label="Waiting for invoice" value={String(toInvoice.length)} deltaLabel={`${formatNumber(toInvoice.reduce((a, r) => a + r.qty, 0))} labels`} />
            </div>
            <DataTable rows={rows} columns={columns} defaultSort={{ key: 'date', dir: 'desc' }} />
          </>
        )}
      </QueryState>
      <NewDispatchDialog
        open={open}
        onOpenChange={setOpen}
        jobs={jobsQ.data?.items ?? []}
        // Live mode refetches the jobs after a save, so their dispatched_qty already counts it.
        localDispatched={api.mode === 'mock' ? added : []}
        onSaved={(d) => {
          setAdded((a) => [d, ...a])
          if (api.mode === 'live') {
            q.refetch()
            jobsQ.refetch()
          }
          setOpen(false)
        }}
        onChallan={openChallan}
      />
      <ChallanPreview dispatch={preview} onClose={() => setPreview(null)} />
    </div>
  )
}

function NewDispatchDialog({
  open,
  onOpenChange,
  jobs,
  localDispatched,
  onSaved,
  onChallan,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  jobs: Job[]
  localDispatched: Dispatch[]
  onSaved: (d: Dispatch) => void
  onChallan: (d: Dispatch) => void
}) {
  const empty = { job_card: '', qty: '', boxes: '', vehicle_no: '', transporter: '', lr_no: '', freight: '', date: todayIso() }
  const [form, setForm] = useState(empty)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<{ status: number | null; message: string } | null>(null)
  const set = (k: keyof typeof form, v: string) => {
    setForm((f) => ({ ...f, [k]: v }))
    setError(null)
  }

  const dispatchedOf = (j: Job) => j.dispatched_qty + localDispatched.filter((d) => d.job_card === j.job_card).reduce((a, d) => a + d.qty, 0)
  const eligible = jobs.filter((j) => j.qc_approved > 0)
  const job = jobs.find((j) => j.job_card === form.job_card)
  const approved = job?.qc_approved ?? 0
  const already = job ? dispatchedOf(job) : 0
  const balance = approved - already
  const qty = Number(form.qty)
  const over = !!job && qty > balance

  async function submit() {
    setError(null)
    if (!job || !(qty > 0) || !form.vehicle_no.trim() || !form.transporter) {
      setError({ status: null, message: 'Choose a job, enter quantity, vehicle and transporter.' })
      return
    }
    const body: DispatchCreate = {
      date: form.date,
      job_card: job.job_card,
      qty,
      boxes: Number(form.boxes) || undefined,
      vehicle_no: form.vehicle_no.trim().toUpperCase(),
      transporter: form.transporter,
      freight: Number(form.freight) || 0,
      lr_no: form.lr_no.trim() || undefined,
    }
    setSaving(true)
    try {
      // Mock mode has no backend: apply the same guard the API returns as 409 (SPEC §2).
      if (api.mode === 'mock' && already + qty > approved)
        throw new ApiError(
          409,
          `Dispatch above QC approved for ${job.job_card}: approved ${approved}, already dispatched ${already}, requested ${qty}`,
        )
      const res = await api.post<Dispatch>('/api/dispatch', body)
      const row: Dispatch =
        api.mode === 'mock'
          ? {
              ...res,
              ...body,
              boxes: body.boxes ?? 0,
              lr_no: body.lr_no ?? '',
              client_id: job.client_id,
              client_name: job.client_name,
              qc_approved: approved,
              dispatched_before: already,
              balance_after: approved - already - qty,
              status: 'dispatched',
              invoice_id: null,
            }
          : res
      onSaved(row)
      setForm(empty)
      toast.success(`${row.id} created`, {
        description: `${formatNumber(row.qty)} labels to ${row.client_name}`,
        action: { label: 'Challan', onClick: () => onChallan(row) },
      })
    } catch (e) {
      setError(describeError(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>New dispatch</DialogTitle>
          <DialogDescription>You can only send what QC has approved and not yet dispatched.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Job card" htmlFor="dc-job" className="sm:col-span-2">
            <Select
              id="dc-job"
              value={form.job_card}
              onValueChange={(v) => set('job_card', v)}
              placeholder="Choose job"
              options={eligible.map((j) => ({
                value: j.job_card,
                label: `${j.job_card} · ${j.client_name} · ${formatNumber(j.qc_approved - dispatchedOf(j))} available`,
              }))}
            />
          </Field>
        </div>
        {job && (
          <div className="grid grid-cols-3 gap-3 rounded-lg border border-border bg-surface-muted p-4">
            <div>
              <p className="text-xs text-muted-foreground">QC approved</p>
              <p className="tabular text-lg font-semibold text-foreground">{formatNumber(approved)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Already dispatched</p>
              <p className="tabular text-lg font-semibold text-foreground">{formatNumber(already)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Can dispatch now</p>
              <p className={cn('tabular text-lg font-semibold', balance > 0 ? 'text-ok-foreground' : 'text-danger-foreground')}>
                {formatNumber(balance)}
              </p>
            </div>
          </div>
        )}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Quantity (labels)" htmlFor="dc-qty" error={over ? `More than the ${formatNumber(balance)} available` : undefined}>
            <Input
              id="dc-qty"
              type="number"
              inputMode="numeric"
              min={0}
              value={form.qty}
              onChange={(e) => set('qty', e.target.value)}
              aria-invalid={over || undefined}
              className={cn('tabular', over && 'border-danger')}
            />
          </Field>
          <Field label="Boxes" htmlFor="dc-boxes">
            <Input id="dc-boxes" type="number" inputMode="numeric" min={0} value={form.boxes} onChange={(e) => set('boxes', e.target.value)} />
          </Field>
          <Field label="Transporter" htmlFor="dc-trans">
            <Select id="dc-trans" value={form.transporter} onValueChange={(v) => set('transporter', v)} placeholder="Choose" options={TRANSPORTERS.map((t) => ({ value: t, label: t }))} />
          </Field>
          <Field label="Vehicle no." htmlFor="dc-veh">
            <Input id="dc-veh" value={form.vehicle_no} onChange={(e) => set('vehicle_no', e.target.value)} placeholder="MH12 AB 1234" />
          </Field>
          <Field label="LR no." htmlFor="dc-lr">
            <Input id="dc-lr" value={form.lr_no} onChange={(e) => set('lr_no', e.target.value)} />
          </Field>
          <Field label="Freight (₹)" htmlFor="dc-freight">
            <Input id="dc-freight" type="number" inputMode="decimal" min={0} value={form.freight} onChange={(e) => set('freight', e.target.value)} />
          </Field>
        </div>
        {error && (
          <InlineAlert title={error.status === 409 ? 'Blocked: above QC approved (409)' : error.status ? `Rejected (${error.status})` : 'Check the form'}>
            {error.message}
          </InlineAlert>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Create challan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ChallanPreview({ dispatch: d, onClose }: { dispatch: Dispatch | null; onClose: () => void }) {
  return (
    <Dialog open={!!d} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Delivery challan {d?.id}</DialogTitle>
          <DialogDescription>Preview (demo mode). In live mode this opens the PDF from the API.</DialogDescription>
        </DialogHeader>
        {d && (
          <div className="rounded-lg border border-border-strong bg-surface p-6 text-sm">
            <div className="flex items-start justify-between gap-4 border-b border-border pb-4">
              <div>
                <p className="text-lg font-semibold text-foreground">Pro Labels</p>
                <p className="text-muted-foreground">Label printing &amp; converting</p>
              </div>
              <div className="text-right">
                <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">Delivery challan</p>
                <p className="tabular text-md font-semibold text-foreground">{d.id}</p>
                <p className="text-muted-foreground">{formatDate(d.date)}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 border-b border-border py-4">
              <div>
                <p className="text-xs text-muted-foreground">Consignee</p>
                <p className="font-medium text-foreground">{d.client_name}</p>
                <p className="text-muted-foreground">{d.client_id}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Transport</p>
                <p className="text-foreground">{d.transporter}</p>
                <p className="text-muted-foreground">
                  {d.vehicle_no} · LR {d.lr_no || '—'}
                </p>
              </div>
            </div>
            <table className="my-4 w-full">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium">Job card</th>
                  <th className="py-2 font-medium">Description</th>
                  <th className="py-2 text-right font-medium">Boxes</th>
                  <th className="py-2 text-right font-medium">Qty</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border">
                  <td className="py-2.5 font-medium">{d.job_card}</td>
                  <td className="py-2.5">Printed self-adhesive labels</td>
                  <td className="tabular py-2.5 text-right">{d.boxes}</td>
                  <td className="tabular py-2.5 text-right font-semibold">{formatNumber(d.qty)}</td>
                </tr>
              </tbody>
            </table>
            <div className="flex items-end justify-between gap-4">
              <div className="text-xs text-muted-foreground">
                <p>
                  QC approved {formatNumber(d.qc_approved)} · balance after this challan {formatNumber(d.balance_after)}
                </p>
                <p>Freight {formatINRShort(d.freight)} · not a tax invoice</p>
              </div>
              <div className="text-right">
                <div className="mb-1 h-10 w-36 border-b border-border-strong" />
                <p className="text-xs text-muted-foreground">Authorised signatory</p>
              </div>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => window.print()}>
            <Printer aria-hidden /> Print
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
