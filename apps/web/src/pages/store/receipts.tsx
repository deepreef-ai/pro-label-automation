import { useMemo, useState } from 'react'
import { PackagePlus } from 'lucide-react'
import type { Grn, GrnCreate, Item, Settings, Vendor } from '@contract/types'
import { api, useApi } from '@/lib/api'
import { formatDate, formatINR, formatNumber, formatPercent } from '@/lib/format'
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
  QueryState,
  Select,
  StatusChip,
  TableSkeleton,
  toast,
} from '@/components/ui'
import { describeError, InlineAlert, todayIso } from './common'

export function ReceiptsTab() {
  const q = useApi<Grn[]>('/api/store/grns')
  const [added, setAdded] = useState<Grn[]>([])
  const [open, setOpen] = useState(false)

  const columns: Column<Grn>[] = [
    {
      key: 'id',
      header: 'GRN',
      cell: (r) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {r.id} <DemoBadge show={r.is_demo} />
        </span>
      ),
    },
    { key: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    {
      key: 'vendor_name',
      header: 'Vendor / bill',
      cell: (r) => (
        <div>
          <p>{r.vendor_name}</p>
          <p className="text-xs text-muted-foreground">{r.bill_no}</p>
        </div>
      ),
    },
    { key: 'item_name', header: 'Item' },
    { key: 'qty', header: 'Qty', align: 'right', cell: (r) => `${formatNumber(r.qty, 2)} ${r.uom}` },
    { key: 'rate', header: 'Rate', align: 'right', cell: (r) => formatINR(r.rate) },
    {
      key: 'rate_diff_pct',
      header: 'Rate check',
      cell: (r) =>
        r.rate_flag ? (
          <StatusChip tone="danger" size="sm">
            {formatPercent(r.rate_diff_pct, { signed: true })} vs {formatINR(r.item_rate)}
          </StatusChip>
        ) : (
          <StatusChip tone="ok" size="sm">
            OK {r.rate_diff_pct !== 0 && formatPercent(r.rate_diff_pct, { signed: true })}
          </StatusChip>
        ),
    },
    { key: 'amount', header: 'Amount', align: 'right', cell: (r) => formatINR(r.amount) },
    {
      key: 'roll_ids',
      header: 'Rolls',
      sortable: false,
      cell: (r) =>
        r.roll_ids.length ? <span className="font-mono text-xs">{r.roll_ids.join(', ')}</span> : <span className="text-muted-foreground">—</span>,
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Goods received this month. Rates more than 5% away from the item rate are flagged.
        </p>
        <Button onClick={() => setOpen(true)}>
          <PackagePlus aria-hidden /> Record GRN
        </Button>
      </div>
      <QueryState query={q} loading={<TableSkeleton />}>
        {(rows) => <DataTable rows={[...added, ...rows]} columns={columns} defaultSort={{ key: 'date', dir: 'desc' }} />}
      </QueryState>
      <GrnDialog open={open} onOpenChange={setOpen} onSaved={(g) => setAdded((a) => [g, ...a])} />
    </div>
  )
}

function GrnDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onSaved: (g: Grn) => void
}) {
  const items = useApi<Item[]>(open ? '/api/items' : null)
  const vendors = useApi<Vendor[]>(open ? '/api/vendors' : null)
  const settings = useApi<Settings>(open ? '/api/settings' : null)
  const tol = settings.data?.grn_rate_tol ?? 0.05

  const [form, setForm] = useState({ date: todayIso(), vendor_id: '', bill_no: '', item_id: '', qty: '', rate: '', rolls: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const item = items.data?.find((i) => i.id === form.item_id)
  const rate = Number(form.rate)
  const qty = Number(form.qty)
  const diff = item && rate > 0 ? (rate - item.rate) / item.rate : null
  const rateFlag = diff !== null && Math.abs(diff) > tol
  const rollLengths = useMemo(
    () =>
      form.rolls
        .split(/[,\s]+/)
        .map(Number)
        .filter((n) => Number.isFinite(n) && n > 0),
    [form.rolls],
  )
  const isRollItem = item?.group === 'Paper & Film'
  const amount = qty > 0 && rate > 0 ? qty * rate * (item?.rate_unit === 'per_sqm' && item.width_mm ? item.width_mm / 1000 : 1) : 0

  const missing = !form.vendor_id || !form.item_id || !form.bill_no.trim() || !(qty > 0) || !(rate > 0)

  async function submit() {
    setError(null)
    if (missing) {
      setError('Fill vendor, bill number, item, quantity and rate.')
      return
    }
    const body: GrnCreate = {
      date: form.date,
      vendor_id: form.vendor_id,
      bill_no: form.bill_no.trim(),
      item_id: form.item_id,
      qty,
      rate,
      ...(isRollItem && rollLengths.length ? { roll_lengths_m: rollLengths } : {}),
    }
    setSaving(true)
    try {
      const res = await api.post<Grn>('/api/store/grns', body)
      const vendor = vendors.data?.find((v) => v.id === form.vendor_id)
      // Mock mode returns a fixed example; show what the user entered.
      const row: Grn =
        api.mode === 'mock'
          ? {
              ...res,
              ...body,
              vendor_name: vendor?.name ?? res.vendor_name,
              item_name: item?.name ?? res.item_name,
              uom: item?.uom ?? res.uom,
              item_rate: item?.rate ?? res.item_rate,
              rate_diff_pct: diff ?? 0,
              rate_flag: rateFlag,
              amount: Math.round(amount * 100) / 100,
              roll_ids: rollLengths.length ? res.roll_ids.slice(0, rollLengths.length) : [],
            }
          : res
      onSaved(row)
      toast.success(`${row.id} recorded`, {
        description: row.rate_flag ? 'Rate is outside tolerance. The payables check will review it.' : undefined,
      })
      setForm({ date: todayIso(), vendor_id: '', bill_no: '', item_id: '', qty: '', rate: '', rolls: '' })
      onOpenChange(false)
    } catch (e) {
      const { status, message } = describeError(e)
      setError(status ? `${status} · ${message}` : message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Record GRN</DialogTitle>
          <DialogDescription>Goods received against a supplier bill. Paper and film get numbered rolls.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Date" htmlFor="grn-date">
            <Input id="grn-date" type="date" value={form.date} onChange={(e) => set('date', e.target.value)} />
          </Field>
          <Field label="Vendor" htmlFor="grn-vendor">
            <Select
              id="grn-vendor"
              value={form.vendor_id}
              onValueChange={(v) => set('vendor_id', v)}
              placeholder={vendors.loading ? 'Loading…' : 'Choose vendor'}
              options={(vendors.data ?? []).map((v) => ({ value: v.id, label: v.name }))}
            />
          </Field>
          <Field label="Bill no." htmlFor="grn-bill">
            <Input id="grn-bill" value={form.bill_no} onChange={(e) => set('bill_no', e.target.value)} placeholder="e.g. SGF/1140" />
          </Field>
          <Field label="Item" htmlFor="grn-item">
            <Select
              id="grn-item"
              value={form.item_id}
              onValueChange={(v) => set('item_id', v)}
              placeholder={items.loading ? 'Loading…' : 'Choose item'}
              options={(items.data ?? []).map((i) => ({ value: i.id, label: `${i.name} · ${formatINR(i.rate)}/${i.uom}` }))}
            />
          </Field>
          <Field label={`Quantity${item ? ` (${item.uom})` : ''}`} htmlFor="grn-qty">
            <Input id="grn-qty" type="number" inputMode="decimal" min={0} value={form.qty} onChange={(e) => set('qty', e.target.value)} />
          </Field>
          <Field
            label="Bill rate (₹)"
            htmlFor="grn-rate"
            hint={item ? `Item master rate ${formatINR(item.rate)} · tolerance ±${formatPercent(tol, { digits: 0 })}` : undefined}
          >
            <Input id="grn-rate" type="number" inputMode="decimal" min={0} step="0.01" value={form.rate} onChange={(e) => set('rate', e.target.value)} />
          </Field>
          {isRollItem && (
            <Field
              label="Roll lengths (m)"
              htmlFor="grn-rolls"
              hint="One number per roll, separated by commas. Each roll gets an R-YYYY-#### barcode."
              className="sm:col-span-2"
            >
              <Input id="grn-rolls" value={form.rolls} onChange={(e) => set('rolls', e.target.value)} placeholder="1000, 1000" />
            </Field>
          )}
        </div>

        {rateFlag && item && diff !== null && (
          <InlineAlert tone="warn" title={`Rate is ${formatPercent(diff, { signed: true })} vs the item master`}>
            Bill rate {formatINR(rate)} against {formatINR(item.rate)}. Above the ±{formatPercent(tol, { digits: 0 })} tolerance:
            the GRN will be saved with a rate flag for accounts to check before paying the bill.
          </InlineAlert>
        )}
        {isRollItem && rollLengths.length > 0 && qty > 0 && Math.abs(rollLengths.reduce((a, b) => a + b, 0) - qty) > 0.5 && (
          <InlineAlert tone="warn">
            Roll lengths add up to {formatNumber(rollLengths.reduce((a, b) => a + b, 0))} m, not {formatNumber(qty)} m.
          </InlineAlert>
        )}
        {error && <InlineAlert title="Could not save">{error}</InlineAlert>}

        <div className="flex items-center justify-between gap-3 rounded-md bg-surface-muted px-4 py-3 text-sm">
          <span className="text-muted-foreground">Bill amount (before GST)</span>
          <span className="tabular font-semibold text-foreground">{formatINR(amount)}</span>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Save GRN
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
