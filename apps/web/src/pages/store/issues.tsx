import { useState } from 'react'
import { PackageMinus } from 'lucide-react'
import type { Issue, IssueCreate, Item, JobListResponse, Roll } from '@contract/types'
import { api, ApiError, useApi } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatNumber } from '@/lib/format'
import {
  Badge,
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
  QueryState,
  Segmented,
  Select,
  StatusChip,
  TableSkeleton,
  toast,
} from '@/components/ui'
import { describeError, InlineAlert, todayIso } from './common'

type Filter = 'all' | 'missing'

export function IssuesTab({ initialFilter = 'all' }: { initialFilter?: Filter }) {
  const q = useApi<Issue[]>('/api/store/issues')
  const [added, setAdded] = useState<Issue[]>([])
  const [filter, setFilter] = useState<Filter>(initialFilter)
  const [open, setOpen] = useState(false)

  const columns: Column<Issue>[] = [
    {
      key: 'id',
      header: 'Issue',
      cell: (r) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {r.id} <DemoBadge show={r.is_demo} />
        </span>
      ),
    },
    { key: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    {
      key: 'job_card',
      header: 'Job card',
      cell: (r) =>
        r.job_card ? (
          <span className="font-medium">{r.job_card}</span>
        ) : (
          <StatusChip tone="danger" size="sm">
            No job card
          </StatusChip>
        ),
    },
    { key: 'item_name', header: 'Item' },
    {
      key: 'qty',
      header: 'Qty',
      align: 'right',
      cell: (r) => (
        <div>
          <p>
            {formatNumber(r.qty, 2)} {r.uom}
          </p>
          {r.sqm !== null && <p className="text-xs text-muted-foreground">{formatNumber(r.sqm, 2)} sq m</p>}
        </div>
      ),
    },
    {
      key: 'roll_id',
      header: 'Roll',
      cell: (r) => (r.roll_id ? <span className="font-mono text-xs">{r.roll_id}</span> : <span className="text-muted-foreground">—</span>),
    },
    { key: 'issued_to', header: 'Issued to' },
    { key: 'value', header: 'Value', align: 'right', cell: (r) => formatINR(r.value) },
    {
      key: 'source',
      header: 'Source',
      cell: (r) => <Badge tone={r.source === 'app' ? 'accent' : 'neutral'} size="sm">{r.source === 'app' ? 'App' : 'ERP import'}</Badge>,
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          aria-label="Filter issues"
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'All issues' },
            { value: 'missing', label: 'Without job card' },
          ]}
        />
        <Button onClick={() => setOpen(true)}>
          <PackageMinus aria-hidden /> Issue material
        </Button>
      </div>
      <QueryState query={q} loading={<TableSkeleton />}>
        {(rows) => {
          const all = [...added, ...rows]
          const shown = filter === 'missing' ? all.filter((r) => !r.job_card) : all
          const noJc = all.filter((r) => !r.job_card)
          return (
            <>
              {noJc.length > 0 && (
                <InlineAlert tone="warn">
                  {noJc.length} of {all.length} lines ({formatINRShort(noJc.reduce((a, r) => a + r.value, 0))}) came from the old
                  ERP without a job card. Ink and varnish among them go to the monthly ink pool.
                </InlineAlert>
              )}
              <DataTable rows={shown} columns={columns} defaultSort={{ key: 'date', dir: 'desc' }} />
            </>
          )
        }}
      </QueryState>
      <IssueDialog open={open} onOpenChange={setOpen} onSaved={(i) => setAdded((a) => [i, ...a])} />
    </div>
  )
}

function IssueDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onSaved: (i: Issue) => void
}) {
  const items = useApi<Item[]>(open ? '/api/items' : null)
  const jobs = useApi<JobListResponse>(open ? '/api/jobs' : null)
  const rolls = useApi<Roll[]>(open ? '/api/store/rolls' : null)

  const empty = { date: todayIso(), job_card: '', item_id: '', qty: '', roll_id: '', issued_to: '' }
  const [form, setForm] = useState(empty)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<{ status: number | null; message: string } | null>(null)
  const set = (k: keyof typeof form, v: string) => {
    setForm((f) => ({ ...f, [k]: v }))
    if (k === 'job_card') setError(null)
  }

  const item = items.data?.find((i) => i.id === form.item_id)
  const itemRolls = (rolls.data ?? []).filter((r) => r.item_id === form.item_id && r.balance_m > 0)
  const job = jobs.data?.items.find((j) => j.job_card === form.job_card.trim().toUpperCase())
  const qty = Number(form.qty)

  async function submit() {
    setError(null)
    const jc = form.job_card.trim().toUpperCase()
    const body: IssueCreate = {
      date: form.date,
      job_card: jc,
      item_id: form.item_id,
      qty,
      roll_id: form.roll_id || null,
      issued_to: form.issued_to.trim() || undefined,
    }
    setSaving(true)
    try {
      if (!form.item_id || !(qty > 0)) throw new Error('Choose an item and enter a quantity above zero.')
      // Mock mode has no backend, so apply the same rule the API enforces (SPEC §2: store issue must have a valid job card).
      if (api.mode === 'mock') {
        if (!jc) throw new ApiError(400, 'job_card is required: every store issue must be booked to a valid job card')
        if (jobs.data && !job) throw new ApiError(400, `Unknown job card ${jc}: not in the PPIC register`)
      }
      const res = await api.post<Issue>('/api/store/issues', body)
      const row: Issue =
        api.mode === 'mock'
          ? {
              ...res,
              date: body.date,
              job_card: jc,
              item_id: body.item_id,
              item_name: item?.name ?? res.item_name,
              qty,
              uom: item?.uom ?? res.uom,
              sqm: item?.uom === 'm' && item.width_mm ? Math.round(((qty * item.width_mm) / 1000) * 100) / 100 : null,
              roll_id: body.roll_id ?? null,
              rate: item?.rate ?? res.rate,
              value: Math.round(qty * (item?.rate ?? res.rate) * 100) / 100,
              issued_to: body.issued_to ?? job?.machine_name ?? res.issued_to,
              source: 'app',
            }
          : res
      onSaved(row)
      toast.success(`${row.id} issued to ${row.job_card}`)
      setForm(empty)
      onOpenChange(false)
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
          <DialogTitle>Issue material</DialogTitle>
          <DialogDescription>Every issue is booked to a job card, so material cost lands on the right job.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label={
              <>
                Job card <span className="text-danger-foreground">*</span>
              </>
            }
            htmlFor="iss-jc"
            hint={job ? `${job.client_name} · ${job.product} · ${job.machine_name}` : 'Required. e.g. JC-1316'}
            error={error?.status === 400 ? 'Required: enter a valid job card' : undefined}
          >
            <Input
              id="iss-jc"
              list="iss-jobs"
              value={form.job_card}
              onChange={(e) => set('job_card', e.target.value)}
              placeholder="JC-####"
              aria-required
              aria-invalid={error?.status === 400 || undefined}
              className={error?.status === 400 ? 'border-danger' : undefined}
            />
            <datalist id="iss-jobs">
              {(jobs.data?.items ?? [])
                .filter((j) => j.status !== 'closed' && j.status !== 'invoiced')
                .map((j) => (
                  <option key={j.job_card} value={j.job_card}>
                    {j.client_name}
                  </option>
                ))}
            </datalist>
          </Field>
          <Field label="Date" htmlFor="iss-date">
            <Input id="iss-date" type="date" value={form.date} onChange={(e) => set('date', e.target.value)} />
          </Field>
          <Field label="Item" htmlFor="iss-item">
            <Select
              id="iss-item"
              value={form.item_id}
              onValueChange={(v) => setForm((f) => ({ ...f, item_id: v, roll_id: '' }))}
              placeholder={items.loading ? 'Loading…' : 'Choose item'}
              options={(items.data ?? []).map((i) => ({ value: i.id, label: i.name }))}
            />
          </Field>
          <Field label={`Quantity${item ? ` (${item.uom})` : ''}`} htmlFor="iss-qty">
            <Input id="iss-qty" type="number" inputMode="decimal" min={0} value={form.qty} onChange={(e) => set('qty', e.target.value)} />
          </Field>
          {itemRolls.length > 0 && (
            <Field label="Roll" htmlFor="iss-roll" hint="Scan or pick the roll barcode.">
              <Select
                id="iss-roll"
                value={form.roll_id}
                onValueChange={(v) => set('roll_id', v)}
                placeholder="Choose roll"
                options={itemRolls.map((r) => ({ value: r.id, label: `${r.id} · ${formatNumber(r.balance_m)} m left` }))}
              />
            </Field>
          )}
          <Field label="Issued to" htmlFor="iss-to" hint="Machine or person">
            <Input id="iss-to" value={form.issued_to} onChange={(e) => set('issued_to', e.target.value)} placeholder={job?.machine_name ?? 'Gallus EM 280'} />
          </Field>
        </div>
        {job && item && item.uom === 'm' && (
          <p className="text-sm text-muted-foreground">
            Planned for {job.job_card}: {formatNumber(job.planned_m, 1)} m · already issued {formatNumber(job.issued_m, 1)} m.
          </p>
        )}
        {error && (
          <InlineAlert title={error.status ? `Rejected by the API (${error.status})` : 'Could not save'}>{error.message}</InlineAlert>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Issue material
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
