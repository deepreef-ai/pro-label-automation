import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Banknote,
  BriefcaseBusiness,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Inbox,
  Layers,
  Palette,
  Printer,
  ReceiptText,
  Route,
  ScrollText,
  Stamp,
  Truck,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import type { Job360 } from '@contract/types'
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  DemoBadge,
  EmptyState,
  PageHeader,
  QueryState,
  StatusChip,
  Timeline,
  type TimelineItem,
  type TimelineState,
} from '@/components/ui'
import { useApi } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import { JOB_STATUS_LABEL, JOB_STATUS_TONE } from './shared'

export default function Job360Page() {
  const { jobCard = '' } = useParams()
  const q = useApi<Job360>(jobCard ? `/api/jobs/${encodeURIComponent(jobCard)}/360` : null)
  const job = q.data?.job

  return (
    <>
      <PageHeader
        eyebrow={
          <Link to="/jobs" className="inline-flex items-center gap-1 rounded-sm hover:text-foreground">
            <ArrowLeft className="size-3.5" /> Jobs
          </Link>
        }
        title="Job 360"
        meta={
          <>
            {jobCard && <Badge tone="accent">{jobCard}</Badge>}
            {job && <StatusChip tone={JOB_STATUS_TONE[job.status]}>{JOB_STATUS_LABEL[job.status]}</StatusChip>}
            {job && <DemoBadge show={job.is_demo} />}
          </>
        }
        subtitle="One job's full journey from enquiry to profit."
      />
      <QueryState
        query={q}
        empty={
          <Card>
            <EmptyState icon={Route} title={`No record for ${jobCard}`} description="Check the job card number on the Jobs register." />
          </Card>
        }
      >
        {(d) => <Job360View d={d} />}
      </QueryState>
    </>
  )
}

function Job360View({ d }: { d: Job360 }) {
  const j = d.job
  return (
    <div className="space-y-6">
      <Hero d={d} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        <Card className="min-w-0">
          <CardHeader title="Journey" description="Every step, with its date and numbers. Click a step to open its screen." />
          <CardContent>
            <Timeline items={buildTimeline(d)} />
          </CardContent>
        </Card>
        <div className="space-y-6">
          <ProfitCard d={d} />
          {d.checks.length > 0 && (
            <Card>
              <CardHeader title="Rule checks" description="Plant rules applied to this job" />
              <CardContent>
                <ul className="space-y-3">
                  {d.checks.map((c) => (
                    <li key={c.rule} className="flex gap-2.5 text-sm">
                      {c.ok ? (
                        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-label="Pass" />
                      ) : (
                        <XCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-label="Fail" />
                      )}
                      <div>
                        <p className="font-medium text-foreground">{c.label}</p>
                        <p className="text-xs text-muted-foreground">{c.detail}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
      <QuantityChain d={d} />
      <p className="text-xs text-muted-foreground">
        {j.job_card} · {j.machine_name} · {j.ups_across} × {j.ups_along} ups · repeat {j.repeat_mm} mm · {j.units.length} colours
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Hero                                                                */
/* ------------------------------------------------------------------ */

function Hero({ d }: { d: Job360 }) {
  const j = d.job
  const stats: { label: string; value: string; sub?: string }[] = [
    { label: 'Order qty', value: formatNumber(j.order_qty), sub: `₹${j.rate.toFixed(2)} / label` },
    { label: 'PO value', value: formatINR(j.po_value), sub: j.po_no },
    { label: 'Due', value: formatDate(j.due_date), sub: `PO ${formatDate(j.po_date)}` },
    { label: 'Profit', value: formatINRShort(d.cost.profit), sub: `${formatPercent(d.cost.margin_pct)} margin` },
  ]
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{j.client_name}</span>
            <span aria-hidden>·</span>
            <span>{j.client_id}</span>
            {j.flags.includes('client_locked') && <StatusChip tone="danger">Client locked</StatusChip>}
          </div>
          <p className="text-xl font-semibold tracking-tight text-foreground">{j.product}</p>
          <p className="text-sm text-muted-foreground">
            {j.label_size} · {j.material} · {j.machine_name}
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-4">
          {stats.map((s) => (
            <div key={s.label} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{s.label}</dt>
              <dd className="tabular text-lg font-semibold text-foreground">{s.value}</dd>
              {s.sub && <dd className="truncate text-xs text-muted-foreground">{s.sub}</dd>}
            </div>
          ))}
        </dl>
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Timeline                                                            */
/* ------------------------------------------------------------------ */

interface StepDef {
  id: string
  label: string
  icon: LucideIcon
  date?: string | null
  done: boolean
  warn?: boolean
  text: string
  meta?: string
  to?: string
}

function sum<T>(xs: T[], f: (x: T) => number | null | undefined): number {
  return xs.reduce((s, x) => s + (f(x) ?? 0), 0)
}

function buildTimeline(d: Job360): TimelineItem[] {
  const j = d.job
  const tl = (stage: string) => d.timeline.find((t) => t.stage === stage)
  const pressRuns = d.runs.filter((r) => r.machine_type === 'press')
  const usedM = sum(pressRuns, (r) => r.used_m)
  const wastageM = sum(pressRuns, (r) => r.wastage_m)
  const qcChecked = sum(d.qc, (r) => r.checked)
  const qcApproved = sum(d.qc.filter((r) => r.counts_as_approved), (r) => r.approved)
  const qcRejected = sum(d.qc, (r) => r.rejected)
  const firstDate = <T,>(xs: T[], f: (x: T) => string) => (xs.length ? xs.map(f).sort()[0] : null)
  const inv = d.invoices
  const received = sum(inv, (i) => i.received)
  const invTotal = sum(inv, (i) => i.total)
  const outstanding = sum(inv, (i) => i.outstanding)
  const plateCost = sum(d.plates, (p) => p.cost)
  const poEvent = d.timeline.find((t) => t.stage === 'po' && t.ref == null)

  const steps: StepDef[] = [
    {
      id: 'enquiry',
      label: 'Enquiry',
      icon: Inbox,
      date: d.enquiry?.date,
      done: !!d.enquiry,
      text: d.enquiry
        ? `${d.enquiry.id} via ${d.enquiry.source} · ${formatNumber(d.enquiry.qty)} labels · ${d.enquiry.assigned_to}`
        : 'Direct PO, no enquiry logged',
      to: '/marketing',
    },
    {
      id: 'quote',
      label: 'Quote',
      icon: FileText,
      date: d.quote?.date,
      done: !!d.quote,
      text: d.quote
        ? `${d.quote.id} · ₹${d.quote.rate.toFixed(2)}/label · est. margin ${formatPercent(d.quote.margin_pct)}`
        : 'No quote on record',
      meta: d.quote ? formatINR(d.quote.value) : undefined,
      to: '/marketing',
    },
    {
      id: 'po',
      label: 'PO received',
      icon: ScrollText,
      date: j.po_date ?? poEvent?.date,
      done: true,
      text: `${j.po_no} · ${formatNumber(j.order_qty)} labels @ ₹${j.rate.toFixed(2)}${d.quote && Math.abs(d.quote.rate - j.rate) < 0.005 ? ' · rate matches quote' : ''}`,
      meta: formatINR(j.po_value),
      to: '/jobs',
    },
    {
      id: 'job',
      label: 'Job card',
      icon: BriefcaseBusiness,
      date: j.created_on,
      done: true,
      text: `${j.job_card} on ${j.machine_name} · required ${formatNumber(j.required_m, 2)} m, planned ${formatNumber(j.planned_m, 2)} m`,
      to: '/jobs',
    },
    {
      id: 'proof',
      label: 'Proof approved',
      icon: Palette,
      date: d.design?.approved_on ?? d.design?.proof_sent_on ?? tl('design')?.date,
      done: !!d.design?.approved_on,
      text: d.design
        ? d.design.approved_on
          ? `v${d.design.artwork_version} approved by ${d.design.approved_by ?? 'client'}`
          : d.design.proof_sent_on
            ? `Proof v${d.design.artwork_version} sent, waiting for approval`
            : 'Artwork in progress'
        : 'Design not started',
      to: '/design',
    },
    {
      id: 'plates',
      label: 'Plates',
      icon: Stamp,
      date: firstDate(d.plates, (p) => p.made_on),
      done: d.plates.length > 0,
      text: d.plates.length
        ? `${d.plates.length} plates ${d.plates[0].id}…${d.plates[d.plates.length - 1].id}${d.die ? ` · die ${d.die.id}` : ''}`
        : 'No plates made yet',
      meta: d.plates.length ? formatINR(plateCost) : undefined,
      to: '/design?tab=plates',
    },
    {
      id: 'paper',
      label: 'Paper issued',
      icon: Layers,
      date: firstDate(d.issues, (i) => i.date),
      done: d.issues.length > 0,
      text: d.issues.length
        ? `${formatNumber(sum(d.issues, (i) => i.qty))} m ${d.issues[0].item_name} from ${d.rolls.length || d.issues.length} roll${(d.rolls.length || d.issues.length) === 1 ? '' : 's'} (${(d.rolls.length ? d.rolls.map((r) => r.id) : d.issues.map((i) => i.roll_id ?? i.id)).join(', ')})`
        : 'Not issued from store yet',
      meta: d.issues.length ? formatINR(sum(d.issues, (i) => i.value)) : undefined,
      to: '/store',
    },
    {
      id: 'printed',
      label: 'Printed',
      icon: Printer,
      date: firstDate(pressRuns, (r) => r.start),
      done: pressRuns.some((r) => r.status === 'ended'),
      warn: pressRuns.some((r) => r.wastage_flag || r.overprod_flag),
      text: pressRuns.length
        ? `${formatNumber(sum(pressRuns, (r) => r.printed_qty))} printed in ${formatNumber(sum(pressRuns, (r) => r.hours), 1)} h · wastage ${formatNumber(wastageM, 2)} m (${formatPercent(usedM - wastageM > 0 ? wastageM / (usedM - wastageM) : null)})`
        : 'Not on press yet',
      to: '/production',
    },
    {
      id: 'qc',
      label: 'QC',
      icon: ClipboardCheck,
      date: firstDate(d.qc, (r) => r.date),
      done: d.qc.length > 0,
      warn: d.qc.some((r) => !r.counts_as_approved),
      text: d.qc.length
        ? `${formatNumber(qcChecked)} checked · ${formatNumber(qcApproved)} approved · ${formatNumber(qcRejected)} rejected`
        : 'Not inspected yet',
      to: '/qc',
    },
    {
      id: 'dispatch',
      label: 'Dispatched',
      icon: Truck,
      date: firstDate(d.dispatches, (x) => x.date),
      done: d.dispatches.length > 0,
      text: d.dispatches.length
        ? `${d.dispatches.map((x) => `Challan ${x.id}`).join(', ')} · ${formatNumber(sum(d.dispatches, (x) => x.qty))} labels · ${d.dispatches[0].transporter}`
        : 'Nothing dispatched yet',
      meta: d.dispatches.length ? `Freight ${formatINR(sum(d.dispatches, (x) => x.freight))}` : undefined,
      to: '/dispatch',
    },
    {
      id: 'invoice',
      label: 'Invoice',
      icon: ReceiptText,
      date: firstDate(inv, (i) => i.date),
      done: inv.length > 0,
      text: inv.length
        ? `${inv.map((i) => i.id).join(', ')} · taxable ${formatINR(sum(inv, (i) => i.taxable))} + GST ${formatINR(sum(inv, (i) => i.gst))} · due ${formatDate(inv[0].due_date)}`
        : 'Not invoiced yet',
      meta: inv.length ? formatINR(invTotal) : undefined,
      to: '/money?tab=invoices',
    },
    {
      id: 'payment',
      label: 'Payment',
      icon: Banknote,
      date: undefined,
      done: inv.length > 0 && outstanding <= 0.005,
      warn: inv.some((i) => i.days_past_due > 0 && i.outstanding > 0),
      text: !inv.length
        ? 'Waiting for invoice'
        : outstanding <= 0.005
          ? `Paid in full · ${formatINR(received)} received`
          : `${formatINR(outstanding)} outstanding${received > 0 ? ` · ${formatINR(received)} received` : ''} · ${
              inv.some((i) => i.days_past_due > 0) ? `${Math.max(...inv.map((i) => i.days_past_due))} days past due` : `due ${formatDate(inv[0].due_date)}`
            }`,
      meta: inv.length ? formatINR(received) : undefined,
      to: '/money',
    },
  ]

  const firstOpen = steps.findIndex((s) => !s.done)
  return steps.map((s, i) => {
    const state: TimelineState = s.done ? (s.warn ? 'warn' : 'done') : s.warn ? 'danger' : i === firstOpen ? 'current' : 'pending'
    return {
      id: s.id,
      icon: s.done && !s.warn ? undefined : s.icon,
      state,
      date: s.date ?? (s.done ? undefined : 'Pending'),
      title: s.to ? (
        <Link to={s.to} className="group inline-flex items-center gap-1.5 rounded-sm hover:text-accent">
          {s.label}
          <ArrowRight className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" aria-hidden />
        </Link>
      ) : (
        s.label
      ),
      description: s.text,
      meta: s.meta,
    }
  })
}

/* ------------------------------------------------------------------ */
/* Profit                                                              */
/* ------------------------------------------------------------------ */

function ProfitCard({ d }: { d: Job360 }) {
  const c = d.cost
  const lines: { label: string; value: number }[] = [
    { label: 'Paper / material', value: c.material },
    { label: 'Plates', value: c.plates },
    { label: 'Ink', value: c.ink },
    { label: 'Salaries (press crew)', value: c.salaries },
    { label: 'Freight', value: c.freight },
    { label: 'Admin share', value: c.admin_share },
    { label: 'Direct overhead', value: c.direct_overhead },
  ]
  const totalCost = lines.reduce((s, l) => s + l.value, 0)
  const scale = Math.max(c.revenue, totalCost, 1)
  let running = c.revenue
  const loss = c.profit < 0

  return (
    <Card>
      <CardHeader
        title="Profit"
        description={`Revenue from ${c.revenue_basis === 'invoiced' ? 'invoiced value' : 'PO value (not yet invoiced)'}`}
        actions={<StatusChip tone={loss ? 'danger' : c.margin_pct < 0.1 ? 'warn' : 'ok'}>{formatPercent(c.margin_pct)} margin</StatusChip>}
      />
      <CardContent className="space-y-4">
        <div className="flex items-baseline justify-between">
          <span className="text-sm text-muted-foreground">Profit</span>
          <span className={cn('tabular text-2xl font-semibold', loss ? 'text-danger-foreground' : 'text-foreground')}>
            {formatINR(c.profit)}
          </span>
        </div>
        {/* Waterfall: revenue bar, then each cost steps down from what is left. */}
        <ul className="space-y-1.5" aria-label="Revenue to profit waterfall">
          <WaterfallRow label="Revenue" value={c.revenue} left={0} width={c.revenue / scale} tone="revenue" />
          {lines.map((l) => {
            const end = running - l.value
            const row = (
              <WaterfallRow
                key={l.label}
                label={l.label}
                value={-l.value}
                left={Math.max(0, end) / scale}
                width={l.value / scale}
                tone="cost"
              />
            )
            running = end
            return row
          })}
          <WaterfallRow label="Profit" value={c.profit} left={0} width={Math.abs(c.profit) / scale} tone={loss ? 'loss' : 'profit'} strong />
        </ul>
        <p className="text-xs text-muted-foreground">
          Total cost {formatINR(totalCost)} · profit = revenue − all costs
        </p>
      </CardContent>
    </Card>
  )
}

function WaterfallRow({
  label,
  value,
  left,
  width,
  tone,
  strong,
}: {
  label: string
  value: number
  left: number
  width: number
  tone: 'revenue' | 'cost' | 'profit' | 'loss'
  strong?: boolean
}) {
  return (
    <li className={cn('grid grid-cols-[8.5rem_minmax(0,1fr)_5.5rem] items-center gap-3 text-sm', strong && 'border-t border-border pt-2')}>
      <span className={cn('truncate', strong ? 'font-semibold text-foreground' : 'text-muted-foreground')}>{label}</span>
      <div className="relative h-4 rounded-sm bg-surface-sunken" aria-hidden>
        <div
          className={cn(
            'absolute inset-y-0 rounded-sm',
            tone === 'revenue' && 'bg-chart-1',
            tone === 'cost' && 'bg-chart-3/80',
            tone === 'profit' && 'bg-chart-4',
            tone === 'loss' && 'bg-danger',
          )}
          style={{ left: `${left * 100}%`, width: `${Math.max(width * 100, 0.75)}%` }}
        />
      </div>
      <span className={cn('tabular text-right', strong ? 'font-semibold text-foreground' : 'text-foreground')}>
        {value < 0 ? `−${formatINRShort(-value)}` : formatINRShort(value)}
      </span>
    </li>
  )
}

/* ------------------------------------------------------------------ */
/* Quantities chain                                                    */
/* ------------------------------------------------------------------ */

function QuantityChain({ d }: { d: Job360 }) {
  const j = d.job
  const pressRuns = d.runs.filter((r) => r.machine_type === 'press')
  const used = pressRuns.length ? sum(pressRuns, (r) => r.used_m) : null
  const wastage = pressRuns.length ? sum(pressRuns, (r) => r.wastage_m) : null
  const issuedFromStore = d.issues.length ? sum(d.issues, (i) => i.qty) : j.issued_m
  const rejected = sum(d.qc, (r) => r.rejected)

  const nodes: { label: string; value: string; note?: string; noteTone?: 'muted' | 'warn' | 'ok' }[] = [
    { label: 'Issued', value: `${formatNumber(issuedFromStore)} m`, note: `plan ${formatNumber(j.planned_m)} m` },
    {
      label: 'Used on press',
      value: used != null ? `${formatNumber(used)} m` : '—',
      note: wastage != null ? `${formatNumber(wastage, 2)} m wastage` : undefined,
      noteTone: pressRuns.some((r) => r.wastage_flag) ? 'warn' : 'muted',
    },
    {
      label: 'Printed',
      value: formatNumber(j.printed_qty),
      note: `order ${formatNumber(j.order_qty)}`,
      noteTone: pressRuns.some((r) => r.overprod_flag) ? 'warn' : 'muted',
    },
    { label: 'QC approved', value: formatNumber(j.qc_approved), note: rejected ? `${formatNumber(rejected)} rejected` : undefined },
    {
      label: 'Dispatched',
      value: formatNumber(j.dispatched_qty),
      note: j.qc_approved - j.dispatched_qty > 0 ? `${formatNumber(j.qc_approved - j.dispatched_qty)} in stock` : undefined,
    },
    {
      label: 'Invoiced',
      value: formatNumber(j.invoiced_qty),
      note: j.dispatched_qty - j.invoiced_qty > 0 ? `${formatNumber(j.dispatched_qty - j.invoiced_qty)} not billed` : 'all billed',
      noteTone: j.dispatched_qty - j.invoiced_qty > 0 ? 'warn' : 'ok',
    },
  ]

  return (
    <Card>
      <CardHeader title="Quantities" description="Paper in metres, then labels — each step can only be less than the one before." />
      <CardContent>
        <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {nodes.map((n, i) => (
            <li key={n.label} className="relative">
              <div className="h-full rounded-md border border-border bg-surface-muted px-3 py-3">
                <p className="text-xs text-muted-foreground">{n.label}</p>
                <p className="tabular text-lg font-semibold text-foreground">{n.value}</p>
                {n.note && (
                  <p
                    className={cn(
                      'text-xs',
                      n.noteTone === 'warn' ? 'text-warn-foreground' : n.noteTone === 'ok' ? 'text-ok-foreground' : 'text-muted-foreground',
                    )}
                  >
                    {n.note}
                  </p>
                )}
              </div>
              {i < nodes.length - 1 && (
                <ArrowRight
                  className="absolute top-1/2 -right-3 z-[1] hidden size-3.5 -translate-y-1/2 text-subtle-foreground xl:block"
                  aria-hidden
                />
              )}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
