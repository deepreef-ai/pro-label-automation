import { useState } from 'react'
import { Camera, CheckCircle2, ScanSearch } from 'lucide-react'
import type { JobListResponse, QcCreate, QcRow } from '@contract/types'
import { api, ApiError, useApi } from '@/lib/api'
import { formatDate, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  type Column,
  DataTable,
  DemoBadge,
  Field,
  Input,
  PageHeader,
  QueryState,
  SectionHeader,
  Select,
  StatusChip,
  TableSkeleton,
  toast,
  type Tone,
} from '@/components/ui'
import { describeError, InlineAlert, todayIso } from '@/pages/store/common'

type Decision = QcCreate['decision']
const DECISIONS: { value: Decision; tone: Tone }[] = [
  { value: 'Approved', tone: 'ok' },
  { value: 'Approved with Deviation', tone: 'ok' },
  { value: 'Hold', tone: 'warn' },
  { value: 'Rework', tone: 'warn' },
  { value: 'Rejected', tone: 'danger' },
]
const NOT_APPROVED: Decision[] = ['Hold', 'Rework', 'Rejected']
const DEFECTS = ['Colour variation', 'Die-cut miss', 'Plate damage marks', 'Registration', 'Smudging', 'Barcode unreadable', 'Other']

function decisionTone(d: string): Tone {
  return DECISIONS.find((x) => x.value === d)?.tone ?? 'neutral'
}

export default function QcPage() {
  const q = useApi<QcRow[]>('/api/qc')
  const [added, setAdded] = useState<QcRow[]>([])

  const columns: Column<QcRow>[] = [
    {
      key: 'id',
      header: 'QC',
      cell: (r) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {r.id} <DemoBadge show={r.is_demo} />
        </span>
      ),
    },
    { key: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    { key: 'job_card', header: 'Job', cell: (r) => `${r.job_card} · ${r.client_name}` },
    { key: 'checked', header: 'Checked', align: 'right', cell: (r) => formatNumber(r.checked) },
    { key: 'approved', header: 'Approved', align: 'right', cell: (r) => formatNumber(r.approved) },
    { key: 'rejected', header: 'Rejected', align: 'right', cell: (r) => formatNumber(r.rejected) },
    { key: 'rejection_pct', header: 'Rej. %', align: 'right', cell: (r) => formatPercent(r.rejection_pct) },
    {
      key: 'decision',
      header: 'Decision',
      cell: (r) => (
        <div className="space-y-1">
          <StatusChip size="sm" tone={decisionTone(r.decision)}>
            {r.decision}
          </StatusChip>
          {!r.counts_as_approved && <p className="text-xs text-danger-foreground">Not dispatchable</p>}
        </div>
      ),
    },
    {
      key: 'defects',
      header: 'Defects',
      sortable: false,
      cell: (r) =>
        r.defects.length ? (
          <span className="text-sm">{r.defects.map((d) => `${d.type} (${formatNumber(d.qty)})`).join(', ')}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: 'inspector', header: 'Inspector' },
  ]

  return (
    <div className="space-y-8">
      <PageHeader title="QC" subtitle="Inspect printed labels: checked, approved and rejected quantities. Only approved quantity can be dispatched." />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <InspectionForm onSaved={(r) => setAdded((a) => [r, ...a])} />
        </div>
        <div className="xl:col-span-2">
          <CameraDemoCard />
        </div>
      </div>
      <section>
        <SectionHeader title="QC log" description="Hold, Rework and Rejected rows do not count as approved." />
        <QueryState query={q} loading={<TableSkeleton />}>
          {(rows) => <DataTable rows={[...added, ...rows]} columns={columns} defaultSort={{ key: 'date', dir: 'desc' }} />}
        </QueryState>
      </section>
    </div>
  )
}

function InspectionForm({ onSaved }: { onSaved: (r: QcRow) => void }) {
  const jobsQ = useApi<JobListResponse>('/api/jobs')
  const qcQ = useApi<QcRow[]>('/api/qc')
  const empty = { job_card: '', checked: '', approved: '', rejected: '', defect: '', inspector: '', notes: '' }
  const [form, setForm] = useState(empty)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const jobs = (jobsQ.data?.items ?? []).filter((j) => j.printed_qty > 0)
  const job = jobs.find((j) => j.job_card === form.job_card)
  const alreadyChecked = (qcQ.data ?? []).filter((r) => r.job_card === form.job_card).reduce((a, r) => a + r.checked, 0)

  const checked = form.checked === '' ? null : Number(form.checked)
  const approved = form.approved === '' ? null : Number(form.approved)
  const rejected = form.rejected === '' ? null : Number(form.rejected)

  const sumError =
    checked !== null && approved !== null && rejected !== null && approved + rejected !== checked
      ? `Approved + rejected = ${formatNumber(approved + rejected)}, must equal checked (${formatNumber(checked)}).`
      : null
  const printedError =
    job && checked !== null && checked > job.printed_qty
      ? `Checked cannot be more than printed (${formatNumber(job.printed_qty)}).`
      : null
  const negative = [checked, approved, rejected].some((n) => n !== null && (n < 0 || !Number.isFinite(n)))
  const complete = !!job && checked !== null && approved !== null && rejected !== null && !!decision && !!form.inspector.trim()
  const valid = complete && !sumError && !printedError && !negative && checked > 0
  const blocked = decision !== null && NOT_APPROVED.includes(decision)

  async function submit() {
    setError(null)
    if (!valid || !decision || checked === null || approved === null || rejected === null) {
      setError('Fill every field and fix the highlighted numbers.')
      return
    }
    const body: QcCreate = {
      date: todayIso(),
      job_card: form.job_card,
      checked,
      approved,
      rejected,
      decision,
      defects: form.defect && rejected > 0 ? [{ type: form.defect, qty: rejected }] : [],
      inspector: form.inspector.trim(),
      notes: form.notes.trim() || undefined,
    }
    setSaving(true)
    try {
      if (api.mode === 'mock' && approved + rejected !== checked)
        throw new ApiError(400, 'approved + rejected must equal checked')
      const res = await api.post<QcRow>('/api/qc', body)
      const row: QcRow =
        api.mode === 'mock'
          ? {
              ...res,
              ...body,
              notes: body.notes ?? '',
              defects: body.defects ?? [],
              client_name: job?.client_name ?? res.client_name,
              run_id: null,
              rejection_pct: checked ? Math.round((rejected / checked) * 10000) / 10000 : 0,
              counts_as_approved: !NOT_APPROVED.includes(decision),
            }
          : res
      onSaved(row)
      toast.success(`${row.id} saved`, {
        description: row.counts_as_approved ? `${formatNumber(row.approved)} labels can now be dispatched.` : 'Held back from dispatch.',
      })
      setForm(empty)
      setDecision(null)
    } catch (e) {
      const { status, message } = describeError(e)
      setError(status ? `${status} · ${message}` : message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader title="New inspection" description="Numbers are checked as you type." actions={<ScanSearch className="size-4 text-subtle-foreground" aria-hidden />} />
      <CardContent className="space-y-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Job card"
            htmlFor="qc-job"
            className="sm:col-span-2"
            hint={
              job
                ? `${job.client_name} · ${job.product} · printed ${formatNumber(job.printed_qty)} · already checked ${formatNumber(alreadyChecked)}`
                : undefined
            }
          >
            <Select
              id="qc-job"
              size="touch"
              value={form.job_card}
              onValueChange={(v) => set('job_card', v)}
              placeholder={jobsQ.loading ? 'Loading…' : 'Choose job'}
              options={jobs.map((j) => ({ value: j.job_card, label: `${j.job_card} · ${j.client_name}` }))}
            />
          </Field>
          <Field label="Checked" htmlFor="qc-checked" error={printedError ?? undefined}>
            <NumInput id="qc-checked" value={form.checked} onChange={(v) => set('checked', v)} invalid={!!printedError} />
          </Field>
          <Field label="Inspector" htmlFor="qc-insp">
            <Input id="qc-insp" inputSize="touch" value={form.inspector} onChange={(e) => set('inspector', e.target.value)} placeholder="QC Inspector A" />
          </Field>
          <Field label="Approved" htmlFor="qc-approved">
            <NumInput id="qc-approved" value={form.approved} onChange={(v) => set('approved', v)} invalid={!!sumError} />
          </Field>
          <Field label="Rejected" htmlFor="qc-rejected">
            <NumInput id="qc-rejected" value={form.rejected} onChange={(v) => set('rejected', v)} invalid={!!sumError} />
          </Field>
          <Field label="Main defect" htmlFor="qc-defect">
            <Select
              id="qc-defect"
              size="touch"
              value={form.defect}
              onValueChange={(v) => set('defect', v)}
              placeholder="None"
              options={DEFECTS.map((d) => ({ value: d, label: d }))}
            />
          </Field>
          <Field label="Notes" htmlFor="qc-notes">
            <Input id="qc-notes" inputSize="touch" value={form.notes} onChange={(e) => set('notes', e.target.value)} />
          </Field>
        </div>

        {checked !== null && approved !== null && rejected !== null && (
          <div
            className={cn(
              'flex items-center gap-2 rounded-md px-3.5 py-2.5 text-sm',
              sumError ? 'bg-danger-soft text-danger-foreground' : 'bg-ok-soft text-ok-foreground',
            )}
            role="status"
          >
            {sumError ?? (
              <>
                <CheckCircle2 className="size-4" aria-hidden /> {formatNumber(approved)} + {formatNumber(rejected)} = {formatNumber(checked)} checked ·
                rejection {checked ? formatPercent(rejected / checked) : '—'}
              </>
            )}
          </div>
        )}

        <div>
          <p className="mb-2 text-sm font-medium text-foreground">Decision</p>
          <div role="radiogroup" aria-label="Decision" className="flex flex-wrap gap-2">
            {DECISIONS.map((d) => {
              const on = decision === d.value
              return (
                <button
                  key={d.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setDecision(d.value)}
                  className={cn(
                    'min-h-11 rounded-full border px-4 text-base font-medium transition-colors',
                    !on && 'border-border bg-surface text-foreground hover:bg-surface-muted',
                    on && d.tone === 'ok' && 'border-ok/40 bg-ok-soft text-ok-foreground',
                    on && d.tone === 'warn' && 'border-warn/40 bg-warn-soft text-warn-foreground',
                    on && d.tone === 'danger' && 'border-danger/40 bg-danger-soft text-danger-foreground',
                  )}
                >
                  {d.value}
                </button>
              )
            })}
          </div>
        </div>

        {blocked && (
          <InlineAlert tone={decision === 'Rejected' ? 'danger' : 'warn'} title={`${decision}: this quantity cannot be dispatched`}>
            {approved ? `${formatNumber(approved)} labels` : 'This lot'} will not count as QC approved until a new inspection approves it.
          </InlineAlert>
        )}
        {error && <InlineAlert title="Could not save">{error}</InlineAlert>}

        <div className="flex justify-end">
          <Button size="touch" onClick={submit} loading={saving} disabled={!valid}>
            Save inspection
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function NumInput({ id, value, onChange, invalid }: { id: string; value: string; onChange: (v: string) => void; invalid?: boolean }) {
  return (
    <Input
      id={id}
      inputSize="touch"
      type="number"
      inputMode="numeric"
      min={0}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      className={cn('tabular', invalid && 'border-danger')}
    />
  )
}

/** Demo of the camera inspection in the full version: an SVG label with a highlighted colour defect. */
function CameraDemoCard() {
  return (
    <Card className="h-full">
      <CardHeader
        title="Camera check (demo)"
        description="In the full version a camera over the rewinder flags defects automatically."
        actions={
          <Badge tone="info" size="sm">
            <Camera className="size-3" aria-hidden /> Full version
          </Badge>
        }
      />
      <CardContent className="space-y-4">
        <div className="overflow-hidden rounded-lg border border-border bg-surface-sunken p-4">
          <svg viewBox="0 0 320 200" className="h-auto w-full" role="img" aria-label="Label image with a colour defect highlighted">
            {/* web + labels */}
            <rect x="0" y="0" width="320" height="200" className="fill-surface-muted" />
            {[0, 1].map((i) => (
              <g key={i} transform={`translate(${20 + i * 150} 20)`}>
                <rect width="130" height="160" rx="10" className="fill-surface stroke-border-strong" strokeWidth="1.5" />
                <rect x="10" y="10" width="110" height="46" rx="4" className="fill-chart-1" opacity={i === 1 ? 0.55 : 1} />
                <text x="65" y="40" textAnchor="middle" className="fill-surface" style={{ font: '600 14px sans-serif' }}>
                  FRESH JUICE
                </text>
                <circle cx="65" cy="96" r="24" className="fill-chart-3" opacity={i === 1 ? 0.6 : 1} />
                <rect x="20" y="128" width="90" height="4" rx="2" className="fill-chart-5" />
                <rect x="30" y="138" width="70" height="4" rx="2" className="fill-chart-5" />
                {Array.from({ length: 14 }).map((_, b) => (
                  <rect key={b} x={34 + b * 4.5} y="146" width={b % 3 === 0 ? 2.5 : 1.5} height="10" className="fill-foreground" />
                ))}
              </g>
            ))}
            {/* defect highlight on the second label */}
            <rect x="174" y="24" width="122" height="104" rx="6" className="fill-none stroke-danger" strokeWidth="3" strokeDasharray="6 4" />
            <rect x="174" y="4" width="118" height="18" rx="3" className="fill-danger" />
            <text x="233" y="17" textAnchor="middle" className="fill-surface" style={{ font: '600 10px sans-serif' }}>
              Colour ΔE 6.2 · 92%
            </text>
          </svg>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Finding</span>
            <StatusChip tone="danger" size="sm">
              Colour variation
            </StatusChip>
          </div>
          <p className="text-muted-foreground">
            Cyan and orange panels are lighter than the approved proof on label 2. The full version would stop the rewinder and add the count to
            “rejected” automatically.
          </p>
          <p className="text-xs text-subtle-foreground">Demo image drawn in the browser. No camera is connected.</p>
        </div>
      </CardContent>
    </Card>
  )
}
