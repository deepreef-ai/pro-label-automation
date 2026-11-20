import { useMemo, useState } from 'react'
import { ArrowDownWideNarrow, BadgeCheck, CreditCard } from 'lucide-react'
import type { CreditorRow, Creditors, Payment, PaymentCreate, SupplierBill } from '@contract/types'
import {
  Badge,
  Button,
  Card,
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
  Select,
  StatusChip,
  toast,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatDate, formatDateShort, formatINR, formatINRShort } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Stat } from './shared'
import { applyCreditors, isMock, moneyStore, todayISO, useMoneyOverlay } from './store'

/** FIFO: oldest bill (by bill date) first. Display only; the backend does the real allocation. */
function previewFifo(bills: SupplierBill[], amount: number) {
  const open = bills.filter((b) => b.balance > 0.005).sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id))
  let left = Math.max(0, amount)
  const allocations: Payment['allocations'] = []
  for (const b of open) {
    if (left <= 0.005) break
    const applied = Math.min(left, b.balance)
    left = Math.round((left - applied) * 100) / 100
    allocations.push({ bill_id: b.id, bill_no: b.bill_no, applied, balance_after: Math.round((b.balance - applied) * 100) / 100 })
  }
  return { allocations, unallocated: left }
}

function DueChip({ bill }: { bill: SupplierBill }) {
  if (bill.balance <= 0.005) return <StatusChip tone="ok">Paid</StatusChip>
  const d = bill.days_to_due
  if (d < 0) return <StatusChip tone="danger">{-d} days overdue</StatusChip>
  if (d === 0) return <StatusChip tone="danger">Due today</StatusChip>
  if (d <= 7) return <StatusChip tone="warn">Due in {d} days</StatusChip>
  return <StatusChip tone="neutral">Due in {d} days</StatusChip>
}

export function CreditorsTab({ initialVendor }: { initialVendor?: string | null }) {
  const overlay = useMoneyOverlay()
  const q = useApi<Creditors>('/api/creditors')
  const [payFor, setPayFor] = useState<string | null>(null)

  return (
    <QueryState query={q} isEmpty={(d) => d.vendors.length === 0}>
      {(raw) => {
        const data = applyCreditors(raw, overlay)
        const vendors = [...data.vendors].sort(
          (a, b) =>
            (a.vendor_id === initialVendor ? -1 : 0) - (b.vendor_id === initialVendor ? -1 : 0) ||
            (a.next_due_date ?? '9').localeCompare(b.next_due_date ?? '9'),
        )
        return (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 rounded-lg border border-border bg-surface p-5 lg:grid-cols-4">
              <Stat label="Payable" value={formatINRShort(data.totals.outstanding)} hint={`As of ${formatDate(data.as_of)}`} />
              <Stat label="Overdue" value={formatINRShort(data.totals.overdue)} tone={data.totals.overdue > 0 ? 'danger' : undefined} />
              <Stat label="Due in 7 days" value={formatINRShort(data.totals.due_7d)} tone="warn" />
              <Stat label="MSME due in 7 days" value={formatINRShort(data.totals.msme_due_7d)} hint="Legal limit: 45 days" tone="warn" />
            </div>

            <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-muted px-4 py-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-2.5">
                <ArrowDownWideNarrow className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                <p>
                  <strong className="text-foreground">Payments clear the oldest bill first (FIFO).</strong> MSME suppliers
                  must be paid within min(credit days, 45) days of the bill date, so their due dates can be earlier than
                  the agreed credit.
                </p>
              </div>
              <Button size="sm" className="self-start sm:self-auto" onClick={() => setPayFor(vendors[0]?.vendor_id ?? '')}>
                <CreditCard />
                Record payment
              </Button>
            </div>

            <div className="space-y-4">
              {vendors.map((v) => (
                <VendorCard key={v.vendor_id} v={v} highlight={v.vendor_id === initialVendor} onPay={() => setPayFor(v.vendor_id)} />
              ))}
            </div>

            <PaymentDialog
              vendors={data.vendors}
              vendorId={payFor}
              onClose={() => setPayFor(null)}
              onPaid={(p) => {
                if (isMock) moneyStore.addPayment(p)
                else q.refetch()
              }}
            />
          </div>
        )
      }}
    </QueryState>
  )
}

function VendorCard({ v, highlight, onPay }: { v: CreditorRow; highlight: boolean; onPay: () => void }) {
  const bills = [...v.bills].sort((a, b) => a.date.localeCompare(b.date))
  return (
    <Card className={cn('overflow-hidden', highlight && 'border-accent')}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4 pb-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-md font-semibold text-foreground">{v.vendor_name}</h3>
            {v.msme && (
              <Badge tone="info" size="sm">
                <BadgeCheck className="size-3" aria-hidden />
                MSME
              </Badge>
            )}
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {v.credit_days}-day credit
            {v.msme && v.effective_credit_days < v.credit_days && ` · capped at ${v.effective_credit_days} days (MSME)`}
            {v.next_due_date && ` · next due ${formatDateShort(v.next_due_date)}`}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-muted-foreground">Outstanding</div>
            <div className="tabular text-lg font-semibold text-foreground">{formatINR(v.outstanding)}</div>
          </div>
          <Button size="sm" variant="secondary" onClick={onPay} disabled={v.outstanding <= 0.005}>
            Record payment
          </Button>
        </div>
      </div>
      <div className="overflow-x-auto border-t border-border">
        <table className="w-full text-base">
          <thead>
            <tr className="bg-surface-muted text-left text-xs text-muted-foreground">
              <th className="px-5 py-2 font-medium">Bill</th>
              <th className="px-4 py-2 font-medium">Bill date</th>
              <th className="px-4 py-2 text-right font-medium">Amount</th>
              <th className="px-4 py-2 text-right font-medium">Paid</th>
              <th className="px-4 py-2 text-right font-medium">Balance</th>
              <th className="px-4 py-2 font-medium">Due date</th>
              <th className="px-5 py-2 font-medium">Due in</th>
            </tr>
          </thead>
          <tbody>
            {bills.map((b) => (
              <tr key={b.id} className="border-t border-border">
                <td className="px-5 py-2.5 font-medium whitespace-nowrap">{b.bill_no}</td>
                <td className="px-4 py-2.5 whitespace-nowrap">{formatDate(b.date)}</td>
                <td className="tabular px-4 py-2.5 text-right">{formatINR(b.amount)}</td>
                <td className="tabular px-4 py-2.5 text-right text-muted-foreground">{formatINR(b.paid)}</td>
                <td className="tabular px-4 py-2.5 text-right font-medium">{formatINR(b.balance)}</td>
                <td className="px-4 py-2.5 whitespace-nowrap">{formatDate(b.due_date)}</td>
                <td className="px-5 py-2.5">
                  <DueChip bill={b} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function PaymentDialog({
  vendors,
  vendorId,
  onClose,
  onPaid,
}: {
  vendors: CreditorRow[]
  vendorId: string | null
  onClose: () => void
  onPaid: (p: Payment) => void
}) {
  const open = vendorId !== null
  const [picked, setPicked] = useState<string>('')
  const [amount, setAmount] = useState('')
  const [mode, setMode] = useState<PaymentCreate['mode']>('neft')
  const [ref, setRef] = useState('')
  const [date, setDate] = useState(todayISO())
  const [busy, setBusy] = useState(false)
  const [lastVendor, setLastVendor] = useState<string | null>(null)

  // Reset the form whenever the dialog opens for a (new) vendor.
  if (vendorId !== lastVendor) {
    setLastVendor(vendorId)
    if (vendorId !== null) {
      setPicked(vendorId)
      setAmount('')
      setRef('')
      setDate(todayISO())
    }
  }

  const vendor = vendors.find((v) => v.vendor_id === picked)
  const amt = Number(amount)
  const preview = useMemo(
    () => (vendor && amt > 0 ? previewFifo(vendor.bills, amt) : null),
    [vendor, amt],
  )
  const valid = !!vendor && amt > 0 && Number.isFinite(amt)

  const submit = async () => {
    if (!valid || !vendor) return
    setBusy(true)
    const body: PaymentCreate = { vendor_id: vendor.vendor_id, date, amount: Math.round(amt * 100) / 100, mode, ref: ref.trim() || undefined }
    try {
      const res = await api.post<Payment>('/api/payments', body)
      const fifo = previewFifo(vendor.bills, body.amount)
      const payment: Payment = isMock
        ? {
            ...res,
            vendor_id: vendor.vendor_id,
            vendor_name: vendor.vendor_name,
            date,
            amount: body.amount,
            mode,
            ref: body.ref ?? '',
            allocations: fifo.allocations,
            unallocated: fifo.unallocated,
          }
        : res
      onPaid(payment)
      const cleared = payment.allocations.filter((a) => a.balance_after <= 0.005).map((a) => a.bill_no)
      toast.success(`${formatINR(payment.amount)} paid to ${payment.vendor_name}`, {
        description: cleared.length ? `Cleared ${cleared.join(', ')}` : `Applied to ${payment.allocations.map((a) => a.bill_no).join(', ')}`,
      })
      onClose()
    } catch (e) {
      toast.error('Could not record the payment', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Record supplier payment</DialogTitle>
          <DialogDescription>The amount is applied to the oldest open bill first.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Supplier" htmlFor="pay-vendor" className="sm:col-span-2">
            <Select
              id="pay-vendor"
              value={picked}
              onValueChange={setPicked}
              options={vendors.map((v) => ({
                value: v.vendor_id,
                label: `${v.vendor_name}${v.msme ? ' (MSME)' : ''} · ${formatINRShort(v.outstanding)} due`,
              }))}
            />
          </Field>
          <Field label="Amount (₹)" htmlFor="pay-amt">
            <Input
              id="pay-amt"
              type="number"
              inputMode="decimal"
              min={0}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={vendor ? String(vendor.outstanding) : ''}
            />
          </Field>
          <Field label="Date" htmlFor="pay-date">
            <Input id="pay-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="Mode" htmlFor="pay-mode">
            <Select
              id="pay-mode"
              value={mode}
              onValueChange={(v) => setMode(v as PaymentCreate['mode'])}
              options={[
                { value: 'neft', label: 'NEFT' },
                { value: 'rtgs', label: 'RTGS' },
                { value: 'cheque', label: 'Cheque' },
                { value: 'upi', label: 'UPI' },
              ]}
            />
          </Field>
          <Field label="Reference" htmlFor="pay-ref">
            <Input id="pay-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="UTR / cheque no." />
          </Field>
        </div>

        <div className="rounded-lg border border-border">
          <div className="border-b border-border bg-surface-muted px-4 py-2 text-xs font-medium text-muted-foreground">
            What this payment clears (oldest first)
          </div>
          {!preview ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">Enter an amount to see which bills it clears.</p>
          ) : preview.allocations.length === 0 ? (
            <EmptyState compact title="No open bills" description="Nothing is outstanding for this supplier." />
          ) : (
            <ol className="divide-y divide-border">
              {preview.allocations.map((a, i) => (
                <li key={a.bill_id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="flex size-5 items-center justify-center rounded-full bg-surface-muted text-2xs font-semibold text-muted-foreground">
                      {i + 1}
                    </span>
                    <span className="font-medium text-foreground">{a.bill_no}</span>
                  </div>
                  <div className="tabular flex items-center gap-3 text-sm">
                    <span>{formatINR(a.applied)}</span>
                    {a.balance_after <= 0.005 ? (
                      <StatusChip tone="ok">Cleared</StatusChip>
                    ) : (
                      <StatusChip tone="warn">{formatINR(a.balance_after)} left</StatusChip>
                    )}
                  </div>
                </li>
              ))}
              {preview.unallocated > 0.005 && (
                <li className="px-4 py-2.5 text-sm text-warn-foreground">
                  {formatINR(preview.unallocated)} is more than the bills due and stays as an advance.
                </li>
              )}
            </ol>
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy} disabled={!valid}>
            Record payment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
