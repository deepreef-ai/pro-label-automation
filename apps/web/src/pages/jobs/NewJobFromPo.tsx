import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, FileUp, Loader2, Sparkles, XCircle } from 'lucide-react'
import type { Enquiry, Job, JobCreate, PoDraft } from '@contract/types'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  type Tone,
  toast,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatDate, formatINR, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

type Step = 'upload' | 'reading' | 'review'

const FIELD_ORDER: { key: keyof JobCreate; label: string; kind: 'text' | 'number' | 'date'; key5?: boolean }[] = [
  { key: 'client_id', label: 'Client', kind: 'text', key5: true },
  { key: 'po_no', label: 'PO number', kind: 'text', key5: true },
  { key: 'po_date', label: 'PO date', kind: 'date' },
  { key: 'order_qty', label: 'Quantity (labels)', kind: 'number', key5: true },
  { key: 'rate', label: 'Rate per label (₹)', kind: 'number', key5: true },
  { key: 'due_date', label: 'Delivery date', kind: 'date', key5: true },
  { key: 'product', label: 'Product', kind: 'text' },
  { key: 'label_size', label: 'Label size', kind: 'text' },
  { key: 'item_id', label: 'Paper item', kind: 'text' },
]

function confidenceTone(c: number): Tone {
  return c >= 0.9 ? 'ok' : c >= 0.75 ? 'warn' : 'danger'
}

export function NewJobFromPoDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">{open && <Flow onClose={() => onOpenChange(false)} />}</DialogContent>
    </Dialog>
  )
}

function Flow({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<Step>('upload')
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<PoDraft | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const enquiries = useApi<Enquiry[]>(step === 'review' ? '/api/enquiries' : null)

  const upload = async (file: File | undefined) => {
    if (!file) return
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please drop the client PO as a PDF file.')
      return
    }
    setError(null)
    setStep('reading')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post<PoDraft>('/api/jobs/from-po', fd)
      if (!res || !res.draft) throw new Error('The PO could not be read. Try another file.')
      const v: Record<string, string> = {}
      for (const f of FIELD_ORDER) {
        const val = res.draft[f.key] ?? res.fields[f.key]?.value
        v[f.key] = val == null ? '' : String(val)
      }
      setDraft(res)
      setValues(v)
      setStep('review')
    } catch (e) {
      setError((e as Error).message)
      setStep('upload')
    }
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    void upload(e.dataTransfer.files?.[0])
  }

  // Rate check against the client's last quote (derived from enquiries: quote value / qty).
  const clientId = values.client_id
  const rate = Number(values.rate)
  const quoted = (Array.isArray(enquiries.data) ? enquiries.data : [])
    .filter((e) => e.client_id === clientId && e.quote_id && e.value && e.qty && (e.status === 'won' || e.status === 'quoted'))
    .sort((a, b) => b.date.localeCompare(a.date))[0]
  const quoteRate = quoted ? Math.round(((quoted.value ?? 0) / quoted.qty) * 100) / 100 : null
  const rateOk = quoteRate != null && rate > 0 ? Math.abs(rate - quoteRate) / quoteRate <= 0.005 : null

  const confirm = async () => {
    if (!draft) return
    const body: JobCreate = {
      ...draft.draft,
      client_id: values.client_id,
      po_no: values.po_no,
      po_date: values.po_date,
      product: values.product,
      label_size: values.label_size,
      item_id: values.item_id,
      due_date: values.due_date,
      order_qty: Number(values.order_qty),
      rate: Number(values.rate),
      enquiry_id: draft.draft.enquiry_id ?? (quoted?.id ?? null),
    }
    if (!body.client_id || !body.po_no || !(body.order_qty > 0) || !(body.rate > 0) || !body.due_date) {
      setError('Client, PO number, quantity, rate and delivery date are needed.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const job = await api.post<Partial<Job>>('/api/jobs', body)
      const jc = job?.job_card
      toast.success(jc ? `Job ${jc} created` : 'Job created', {
        description: `${draft.client_match?.client_name ?? body.client_id} · ${formatNumber(body.order_qty)} labels · ${formatINR(body.order_qty * body.rate)}`,
      })
      onClose()
      if (jc) navigate(`/jobs/${jc}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>New job from PO</DialogTitle>
        <DialogDescription>
          Drop the client&apos;s purchase order. AI reads it into a draft; nothing is saved until you confirm.
        </DialogDescription>
      </DialogHeader>

      {step !== 'review' && (
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload PO PDF"
          onClick={() => step === 'upload' && inputRef.current?.click()}
          onKeyDown={(e) => {
            if ((e.key === 'Enter' || e.key === ' ') && step === 'upload') {
              e.preventDefault()
              inputRef.current?.click()
            }
          }}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'flex min-h-56 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors',
            'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
            dragging ? 'border-accent bg-accent-soft' : 'border-border-strong bg-surface-muted hover:border-accent',
          )}
        >
          {step === 'reading' ? (
            <>
              <Loader2 className="size-8 animate-spin text-accent" aria-hidden />
              <p className="font-medium text-foreground">Reading the PO…</p>
              <p className="text-sm text-muted-foreground">Finding client, PO number, quantity, rate and delivery date.</p>
            </>
          ) : (
            <>
              <div className="flex size-12 items-center justify-center rounded-lg border border-border bg-surface text-accent">
                <FileUp className="size-6" aria-hidden />
              </div>
              <p className="font-medium text-foreground">Drag the PO PDF here, or click to choose</p>
              <p className="text-sm text-muted-foreground">PDF only · one PO at a time</p>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            tabIndex={-1}
            onChange={(e) => {
              void upload(e.target.files?.[0])
              e.target.value = ''
            }}
          />
        </div>
      )}

      {step === 'review' && draft && (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-accent/20 bg-accent-soft px-3 py-2 text-sm text-accent-soft-foreground">
            <Sparkles className="size-4" aria-hidden />
            <span>
              AI draft from <span className="font-medium">{draft.file_name}</span>
            </span>
            {draft.client_match && (
              <Badge tone="accent" size="sm">
                {draft.client_match.client_name} · {formatPercent(draft.client_match.score, { digits: 0 })} match
              </Badge>
            )}
          </div>

          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[560px] border-separate border-spacing-0 text-sm">
              <thead>
                <tr className="bg-surface-muted text-xs text-muted-foreground">
                  <th className="border-b border-border px-3 py-2 text-left font-medium">Field</th>
                  <th className="border-b border-border px-3 py-2 text-left font-medium">Value (edit if wrong)</th>
                  <th className="border-b border-border px-3 py-2 text-left font-medium">Confidence</th>
                  <th className="border-b border-border px-3 py-2 text-left font-medium">Read from PO</th>
                </tr>
              </thead>
              <tbody>
                {FIELD_ORDER.map((f) => {
                  const meta = draft.fields[f.key]
                  const conf = meta?.confidence
                  return (
                    <tr key={f.key} className={cn(f.key5 && 'bg-surface')}>
                      <td className="border-b border-border px-3 py-2 align-middle font-medium whitespace-nowrap text-foreground">
                        {f.label}
                      </td>
                      <td className="border-b border-border px-3 py-2">
                        <Input
                          inputSize="sm"
                          aria-label={f.label}
                          type={f.kind === 'number' ? 'number' : f.kind === 'date' ? 'date' : 'text'}
                          step={f.key === 'rate' ? '0.01' : undefined}
                          value={values[f.key] ?? ''}
                          onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                        />
                        {f.key === 'client_id' && draft.client_match && values.client_id === draft.client_match.client_id && (
                          <p className="mt-1 text-xs text-muted-foreground">{draft.client_match.client_name}</p>
                        )}
                      </td>
                      <td className="border-b border-border px-3 py-2">
                        {conf != null ? (
                          <div className="flex min-w-24 items-center gap-2">
                            <div className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                              <div
                                className={cn(
                                  'h-full rounded-full',
                                  confidenceTone(conf) === 'ok' ? 'bg-ok' : confidenceTone(conf) === 'warn' ? 'bg-warn' : 'bg-danger',
                                )}
                                style={{ width: `${conf * 100}%` }}
                              />
                            </div>
                            <Badge tone={confidenceTone(conf)} size="sm">
                              {formatPercent(conf, { digits: 0 })}
                            </Badge>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">Not on PO</span>
                        )}
                      </td>
                      <td className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
                        {meta?.source_text ? <q>{meta.source_text}</q> : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <RateCheck loading={enquiries.loading} ok={rateOk} rate={rate} quoteRate={quoteRate} quoteId={quoted?.quote_id ?? null} />
            <div className="rounded-md border border-border px-3 py-2.5 text-sm">
              <p className="text-xs text-muted-foreground">PO value</p>
              <p className="tabular text-md font-semibold text-foreground">
                {formatINR((Number(values.order_qty) || 0) * (Number(values.rate) || 0))}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatNumber(Number(values.order_qty) || 0)} labels · delivery {formatDate(values.due_date)}
              </p>
            </div>
          </div>

          {draft.warnings.length > 0 && (
            <ul className="space-y-1.5 rounded-md border border-warn/25 bg-warn-soft px-3 py-2.5 text-sm text-warn-foreground">
              {draft.warnings.map((w) => (
                <li key={w} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && <p className="text-sm text-danger-foreground">{error}</p>}

      <DialogFooter>
        {step === 'review' && (
          <Button variant="ghost" onClick={() => setStep('upload')} className="sm:mr-auto">
            Use another PO
          </Button>
        )}
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        {step === 'review' && (
          <Button onClick={confirm} loading={saving}>
            Confirm &amp; create job
          </Button>
        )}
      </DialogFooter>
    </>
  )
}

function RateCheck({
  loading,
  ok,
  rate,
  quoteRate,
  quoteId,
}: {
  loading: boolean
  ok: boolean | null
  rate: number
  quoteRate: number | null
  quoteId: string | null
}) {
  if (loading && ok === null) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border px-3 py-2.5 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Checking rate against quotes…
      </div>
    )
  }
  if (ok === null || quoteRate == null) {
    return (
      <div className="flex items-start gap-2 rounded-md border border-border px-3 py-2.5 text-sm text-muted-foreground">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
        No earlier quote found for this client. Check the rate by hand.
      </div>
    )
  }
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-md border px-3 py-2.5 text-sm',
        ok ? 'border-ok/20 bg-ok-soft text-ok-foreground' : 'border-danger/20 bg-danger-soft text-danger-foreground',
      )}
    >
      {ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden /> : <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}
      <div>
        <p className="font-medium">{ok ? `Rate matches quote ${quoteId}` : `Rate differs from quote ${quoteId}`}</p>
        <p className="tabular text-xs">
          PO {formatINR(rate)} / label · quote {formatINR(quoteRate)} / label
        </p>
      </div>
    </div>
  )
}
