import { useEffect, useState, type FormEvent } from 'react'
import type { Client, Enquiry, EnquiryCreate, EnquiryStatusUpdate, Quote, QuoteCreate } from '@contract/types'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  Segmented,
  Select,
  Textarea,
  toast,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatINR, formatNumber } from '@/lib/format'
import { LOST_REASONS, QUOTE_VALIDITY_DAYS, SOURCES, addDays, todayISO } from './helpers'

const OTHER_CLIENT = '__other__'

/* ------------------------------------------------------------------ */
/* New enquiry                                                         */
/* ------------------------------------------------------------------ */

export function NewEnquiryDialog({
  open,
  onOpenChange,
  people,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  people: string[]
  onCreated: (e: Enquiry) => void
}) {
  const clients = useApi<Client[]>(open ? '/api/clients' : null)
  const [clientId, setClientId] = useState('')
  const [clientName, setClientName] = useState('')
  const [product, setProduct] = useState('')
  const [size, setSize] = useState('')
  const [qty, setQty] = useState('')
  const [material, setMaterial] = useState('')
  const [colours, setColours] = useState('4')
  const [finish, setFinish] = useState('')
  const [source, setSource] = useState<string>('phone')
  const [assigned, setAssigned] = useState(people[0] ?? '')
  // the people list loads after the dialog mounts: pick the first salesperson once it arrives
  useEffect(() => {
    if (!assigned && people.length) setAssigned(people[0])
  }, [assigned, people])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clientList = Array.isArray(clients.data) ? clients.data : []
  const isOther = clientId === OTHER_CLIENT
  const resolvedName = isOther ? clientName.trim() : (clientList.find((c) => c.id === clientId)?.name ?? '')

  const reset = () => {
    setClientId('')
    setClientName('')
    setProduct('')
    setSize('')
    setQty('')
    setMaterial('')
    setColours('4')
    setFinish('')
    setSource('phone')
    setError(null)
  }

  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    const q = Number(qty)
    if (!resolvedName || !product.trim() || !size.trim() || !material.trim() || !(q > 0)) {
      setError('Client, product, label size, quantity and material are required.')
      return
    }
    const body: EnquiryCreate = {
      client_id: isOther ? null : clientId,
      client_name: resolvedName,
      product: product.trim(),
      label_size: size.trim(),
      qty: q,
      material: material.trim(),
      colours: Number(colours) || 1,
      finish: finish.trim() || 'None',
      source,
      assigned_to: assigned || undefined,
    }
    setSaving(true)
    setError(null)
    try {
      const res = await api.post<Partial<Enquiry>>('/api/enquiries', body)
      const created: Enquiry = {
        id: res?.id ?? `ENQ-${Date.now().toString().slice(-4)}`,
        date: res?.date ?? todayISO(),
        status: 'new',
        quote_id: null,
        value: null,
        lost_reason: null,
        follow_up_on: res?.follow_up_on ?? addDays(todayISO(), 3),
        job_card: null,
        is_demo: res?.is_demo ?? true,
        client_id: body.client_id ?? null,
        client_name: body.client_name,
        product: body.product,
        label_size: body.label_size,
        qty: body.qty,
        material: body.material,
        colours: body.colours,
        finish: body.finish ?? 'None',
        source: source as Enquiry['source'],
        assigned_to: assigned,
      }
      onCreated(created)
      toast.success(`Enquiry ${created.id} added`, { description: `${created.client_name} · ${formatNumber(q)} labels` })
      reset()
      onOpenChange(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>New enquiry</DialogTitle>
          <DialogDescription>Log what the client asked for. You can make a quote right after.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Client" htmlFor="enq-client">
              <Select
                id="enq-client"
                value={clientId}
                onValueChange={setClientId}
                placeholder={clients.loading ? 'Loading clients…' : 'Choose client'}
                options={[
                  ...clientList.map((c) => ({ value: c.id, label: c.lock_status === 'locked' ? `${c.name} (locked)` : c.name })),
                  { value: OTHER_CLIENT, label: 'New client…' },
                ]}
              />
            </Field>
            {isOther ? (
              <Field label="New client name" htmlFor="enq-client-name">
                <Input id="enq-client-name" value={clientName} onChange={(e) => setClientName(e.target.value)} />
              </Field>
            ) : (
              <Field label="Salesperson" htmlFor="enq-person">
                <Select
                  id="enq-person"
                  value={assigned}
                  onValueChange={setAssigned}
                  options={people.map((p) => ({ value: p, label: p }))}
                />
              </Field>
            )}
          </div>
          <Field label="Product" htmlFor="enq-product">
            <Input
              id="enq-product"
              placeholder="e.g. Groundnut oil 1 L label"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Label size" htmlFor="enq-size">
              <Input id="enq-size" placeholder="70 x 90 mm" value={size} onChange={(e) => setSize(e.target.value)} />
            </Field>
            <Field label="Quantity (labels)" htmlFor="enq-qty">
              <Input id="enq-qty" type="number" min={1} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
            </Field>
            <Field label="Colours" htmlFor="enq-colours">
              <Input id="enq-colours" type="number" min={1} max={10} value={colours} onChange={(e) => setColours(e.target.value)} />
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Material" htmlFor="enq-material">
              <Input id="enq-material" placeholder="PP White" value={material} onChange={(e) => setMaterial(e.target.value)} />
            </Field>
            <Field label="Finish" htmlFor="enq-finish">
              <Input id="enq-finish" placeholder="Gloss varnish" value={finish} onChange={(e) => setFinish(e.target.value)} />
            </Field>
          </div>
          <Field label="Source">
            <Segmented
              aria-label="Enquiry source"
              value={source}
              onChange={setSource}
              className="flex-wrap"
              options={SOURCES.map((s) => ({ value: s, label: s === 'whatsapp' ? 'WhatsApp' : s[0].toUpperCase() + s.slice(1) }))}
            />
          </Field>
          {error && <p className="text-sm text-danger-foreground">{error}</p>}
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Add enquiry
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/* ------------------------------------------------------------------ */
/* Make quote                                                          */
/* ------------------------------------------------------------------ */

export function QuoteDialog({
  enquiry,
  onOpenChange,
  onQuoted,
}: {
  enquiry: Enquiry | null
  onOpenChange: (v: boolean) => void
  onQuoted: (e: Enquiry, q: Quote) => void
}) {
  return (
    <Dialog open={!!enquiry} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        {enquiry && <QuoteForm key={enquiry.id} enquiry={enquiry} onClose={() => onOpenChange(false)} onQuoted={onQuoted} />}
      </DialogContent>
    </Dialog>
  )
}

function QuoteForm({
  enquiry,
  onClose,
  onQuoted,
}: {
  enquiry: Enquiry
  onClose: () => void
  onQuoted: (e: Enquiry, q: Quote) => void
}) {
  const [rate, setRate] = useState('')
  const [qty, setQty] = useState(String(enquiry.qty))
  const [validUntil, setValidUntil] = useState(addDays(todayISO(), QUOTE_VALIDITY_DAYS))
  const [notes, setNotes] = useState('Ex-works; GST 18% extra; 30 days credit')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const r = Number(rate)
  const q = Number(qty)
  const value = r > 0 && q > 0 ? Math.round(r * q * 100) / 100 : null

  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    if (!(r > 0) || !(q > 0)) {
      setError('Enter a rate per label and a quantity.')
      return
    }
    const body: QuoteCreate = { rate: r, qty: q, valid_until: validUntil, notes }
    setSaving(true)
    setError(null)
    try {
      const res = await api.post<Partial<Quote>>(`/api/enquiries/${enquiry.id}/quote`, body)
      // Values the user typed win over anything the demo fixture echoes back.
      const quote: Quote = {
        id: res?.id ?? `Q-${enquiry.id.slice(4)}`,
        enquiry_id: enquiry.id,
        date: res?.date ?? todayISO(),
        qty: q,
        rate: r,
        value: value ?? 0,
        cost_estimate: res?.cost_estimate ?? 0,
        margin_pct: res?.margin_pct ?? 0,
        valid_until: validUntil,
        notes,
        status: 'sent',
        is_demo: res?.is_demo ?? true,
      }
      onQuoted({ ...enquiry, status: 'quoted', quote_id: quote.id, value: quote.value }, quote)
      toast.success(`Quote ${quote.id} sent`, { description: `${formatINR(quote.value)} · valid ${QUOTE_VALIDITY_DAYS} days` })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Make quote · {enquiry.id}</DialogTitle>
        <DialogDescription>
          {enquiry.client_name} · {enquiry.product}
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Rate per label (₹)" htmlFor="q-rate">
            <Input
              id="q-rate"
              type="number"
              step="0.01"
              min={0}
              inputMode="decimal"
              placeholder="0.60"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              autoFocus
            />
          </Field>
          <Field label="Quantity" htmlFor="q-qty">
            <Input id="q-qty" type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
          </Field>
        </div>
        <Field label="Valid until" htmlFor="q-valid" hint={`Default is ${QUOTE_VALIDITY_DAYS} days from today.`}>
          <Input id="q-valid" type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
        </Field>
        <Field label="Notes" htmlFor="q-notes">
          <Textarea id="q-notes" className="min-h-16" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="flex items-center justify-between rounded-md border border-border bg-surface-muted px-4 py-3 text-sm">
          <span className="text-muted-foreground">Quote value</span>
          <span className="tabular text-md font-semibold text-foreground">{formatINR(value)}</span>
        </div>
        {error && <p className="text-sm text-danger-foreground">{error}</p>}
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={saving}>
            Send quote
          </Button>
        </DialogFooter>
      </form>
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Mark won / lost                                                     */
/* ------------------------------------------------------------------ */

export function StatusDialog({
  target,
  onOpenChange,
  onUpdated,
}: {
  target: { enquiry: Enquiry; status: 'won' | 'lost' } | null
  onOpenChange: (v: boolean) => void
  onUpdated: (e: Enquiry) => void
}) {
  return (
    <Dialog open={!!target} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        {target && (
          <StatusForm
            key={target.enquiry.id + target.status}
            enquiry={target.enquiry}
            initial={target.status}
            onClose={() => onOpenChange(false)}
            onUpdated={onUpdated}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function StatusForm({
  enquiry,
  initial,
  onClose,
  onUpdated,
}: {
  enquiry: Enquiry
  initial: 'won' | 'lost'
  onClose: () => void
  onUpdated: (e: Enquiry) => void
}) {
  const [status, setStatus] = useState<'won' | 'lost'>(initial)
  const [reason, setReason] = useState(LOST_REASONS[0])
  const [otherReason, setOtherReason] = useState('')
  const [poNo, setPoNo] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    const finalReason = reason === 'Other' ? otherReason.trim() : reason
    if (status === 'lost' && !finalReason) {
      setError('Say why we lost it, so the team can learn from it.')
      return
    }
    const body: EnquiryStatusUpdate =
      status === 'lost' ? { status, reason: finalReason } : { status, ...(poNo.trim() ? { po_no: poNo.trim() } : {}) }
    setSaving(true)
    setError(null)
    try {
      await api.post<Enquiry>(`/api/enquiries/${enquiry.id}/status`, body)
      onUpdated({ ...enquiry, status, lost_reason: status === 'lost' ? finalReason : null, follow_up_on: null })
      if (status === 'won') toast.success(`${enquiry.id} marked won`, { description: 'Create the job from the PO on the Jobs screen.' })
      else toast(`${enquiry.id} marked lost`, { description: finalReason })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Update {enquiry.id}</DialogTitle>
        <DialogDescription>
          {enquiry.client_name} · {formatINR(enquiry.value)}
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        <Segmented
          aria-label="Outcome"
          value={status}
          onChange={setStatus}
          options={[
            { value: 'won', label: 'Won' },
            { value: 'lost', label: 'Lost' },
          ]}
        />
        {status === 'won' ? (
          <Field label="Client PO number (optional)" htmlFor="st-po">
            <Input id="st-po" placeholder="e.g. FJ/2026/140" value={poNo} onChange={(e) => setPoNo(e.target.value)} />
          </Field>
        ) : (
          <>
            <Field label="Reason" htmlFor="st-reason">
              <Select
                id="st-reason"
                value={reason}
                onValueChange={setReason}
                options={LOST_REASONS.map((r) => ({ value: r, label: r }))}
              />
            </Field>
            {reason === 'Other' && (
              <Field label="Describe the reason" htmlFor="st-other">
                <Input id="st-other" value={otherReason} onChange={(e) => setOtherReason(e.target.value)} />
              </Field>
            )}
          </>
        )}
        {error && <p className="text-sm text-danger-foreground">{error}</p>}
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant={status === 'lost' ? 'destructive' : 'primary'} loading={saving}>
            {status === 'won' ? 'Mark won' : 'Mark lost'}
          </Button>
        </DialogFooter>
      </form>
    </>
  )
}
