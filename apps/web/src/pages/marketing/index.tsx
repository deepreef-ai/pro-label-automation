import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Inbox, Percent, Plus, PowerOff, Search, Trophy } from 'lucide-react'
import type { Enquiry, MarketingSummary, Quote, Settings } from '@contract/types'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  type Column,
  DataTable,
  DemoBadge,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  Input,
  KpiCard,
  PageHeader,
  QueryState,
  Segmented,
  Skeleton,
  StatusChip,
  type Tone,
} from '@/components/ui'
import { useApi, type UseApiResult } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatMonth, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import { NewEnquiryDialog, QuoteDialog, StatusDialog } from './dialogs'
import { QUOTE_VALIDITY_DAYS, STATUS_LABEL, STATUS_TONE, addDays, daysUntil } from './helpers'

type StatusFilter = 'all' | Enquiry['status']

/** Settings has no marketing switch in the contract yet; read it defensively. */
function marketingOff(s: Settings | undefined): boolean {
  if (!s) return false
  const x = s as Settings & { marketing_enabled?: boolean; modules?: Record<string, boolean> }
  return x.marketing_enabled === false || x.modules?.marketing === false
}

export default function MarketingPage() {
  const enquiriesQ = useApi<Enquiry[]>('/api/enquiries')
  const summaryQ = useApi<MarketingSummary>('/api/marketing/summary')
  const settingsQ = useApi<Settings>('/api/settings')

  const [added, setAdded] = useState<Enquiry[]>([])
  const [edits, setEdits] = useState<Record<string, Enquiry>>({})
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')
  const [newOpen, setNewOpen] = useState(false)
  const [quoteFor, setQuoteFor] = useState<Enquiry | null>(null)
  const [statusFor, setStatusFor] = useState<{ enquiry: Enquiry; status: 'won' | 'lost' } | null>(null)

  const enquiries = useMemo(() => {
    const base = Array.isArray(enquiriesQ.data) ? enquiriesQ.data : []
    return [...added, ...base].map((e) => edits[e.id] ?? e)
  }, [enquiriesQ.data, added, edits])

  const counts = useMemo(() => {
    const c = { all: enquiries.length, new: 0, quoted: 0, won: 0, lost: 0 }
    for (const e of enquiries) c[e.status]++
    return c
  }, [enquiries])

  const quotesSent = enquiries.filter((e) => e.quote_id).length
  const decided = counts.won + counts.lost
  const conversion = decided ? counts.won / decided : null
  const openPipeline = enquiries.filter((e) => e.status === 'quoted').reduce((s, e) => s + (e.value ?? 0), 0)

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return enquiries.filter(
      (e) =>
        (filter === 'all' || e.status === filter) &&
        (!q || [e.id, e.client_name, e.product, e.assigned_to, e.quote_id ?? ''].some((v) => v.toLowerCase().includes(q))),
    )
  }, [enquiries, filter, search])

  const people = useMemo(() => {
    const set = new Set<string>(summaryQ.data?.by_person.map((p) => p.name) ?? [])
    for (const e of enquiries) set.add(e.assigned_to)
    return [...set].filter(Boolean)
  }, [summaryQ.data, enquiries])

  const save = (e: Enquiry) => setEdits((m) => ({ ...m, [e.id]: e }))

  const validity = (e: Enquiry): string | null => {
    if (e.status !== 'quoted') return null
    return quotes[e.id]?.valid_until ?? addDays(e.date, QUOTE_VALIDITY_DAYS)
  }

  const columns: Column<Enquiry>[] = [
    {
      key: 'id',
      header: 'Enquiry',
      cell: (e) => (
        <div className="flex flex-col gap-0.5">
          <span className="font-medium tabular">{e.id}</span>
          <span className="text-xs text-muted-foreground">{formatDate(e.date)}</span>
        </div>
      ),
    },
    {
      key: 'client_name',
      header: 'Client',
      cell: (e) => (
        <div className="min-w-44">
          <div className="flex items-center gap-2">
            <span className="font-medium">{e.client_name}</span>
            <DemoBadge show={e.is_demo} />
          </div>
          <div className="truncate text-xs text-muted-foreground" title={e.product}>
            {e.product} · {e.label_size} · {e.colours} col
          </div>
        </div>
      ),
    },
    { key: 'qty', header: 'Qty', align: 'right', cell: (e) => formatNumber(e.qty) },
    { key: 'value', header: 'Value', align: 'right', cell: (e) => (e.value != null ? formatINR(e.value) : '—') },
    { key: 'assigned_to', header: 'Salesperson', cell: (e) => <span className="whitespace-nowrap">{e.assigned_to}</span> },
    {
      key: 'status',
      header: 'Status',
      sortValue: (e) => ['new', 'quoted', 'won', 'lost'].indexOf(e.status),
      cell: (e) => (
        <div className="flex flex-col items-start gap-1">
          <StatusChip tone={STATUS_TONE[e.status]}>{STATUS_LABEL[e.status]}</StatusChip>
          {e.status === 'lost' && e.lost_reason && (
            <span className="max-w-48 text-xs text-danger-foreground">{e.lost_reason}</span>
          )}
          {e.status === 'won' && e.job_card && (
            <Link to={`/jobs/${e.job_card}`} className="rounded-sm text-xs font-medium text-accent hover:underline">
              {e.job_card}
            </Link>
          )}
        </div>
      ),
    },
    {
      key: 'validity',
      header: 'Quote validity',
      sortValue: (e) => {
        const v = validity(e)
        return v ? daysUntil(v) : null
      },
      cell: (e) => {
        const v = validity(e)
        if (!v) return <span className="text-sm text-muted-foreground">{e.quote_id ?? '—'}</span>
        return <ValidityChip validUntil={v} quoteId={e.quote_id} />
      },
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      sortable: false,
      align: 'right',
      cell: (e) => <RowActions e={e} onQuote={() => setQuoteFor(e)} onStatus={(status) => setStatusFor({ enquiry: e, status })} />,
    },
  ]

  const summary = summaryQ.data
  const off = marketingOff(settingsQ.data)

  return (
    <>
      <PageHeader
        title="Marketing"
        subtitle="Enquiries, quotes and sales targets — from first call to won order."
        actions={
          <Button onClick={() => setNewOpen(true)} disabled={off}>
            <Plus /> New enquiry
          </Button>
        }
      />

      {off && (
        <div
          role="status"
          className="mb-6 flex items-start gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn-foreground"
        >
          <PowerOff className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div>
            <p className="font-semibold">Marketing is switched off</p>
            <p>This plant does not track enquiries in the app right now. The owner can switch it on in Settings.</p>
          </div>
        </div>
      )}

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Enquiries"
          icon={Inbox}
          loading={enquiriesQ.loading && !enquiriesQ.data}
          value={formatNumber(counts.all)}
          deltaLabel={`${counts.new} waiting for a quote`}
        />
        <KpiCard
          label="Quotes sent"
          icon={FileText}
          loading={enquiriesQ.loading && !enquiriesQ.data}
          value={formatNumber(quotesSent)}
          deltaLabel={`${formatINRShort(openPipeline)} open pipeline`}
        />
        <KpiCard
          label="Won"
          icon={Trophy}
          loading={enquiriesQ.loading && !enquiriesQ.data}
          value={formatNumber(counts.won)}
          deltaLabel={`${counts.lost} lost`}
        />
        <KpiCard
          label="Conversion"
          icon={Percent}
          loading={enquiriesQ.loading && !enquiriesQ.data}
          value={formatPercent(summary?.win_rate ?? conversion)}
          deltaLabel="won ÷ (won + lost)"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section aria-labelledby="enq-title" className="min-w-0 space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 id="enq-title" className="text-lg font-semibold text-foreground">
              Enquiries
            </h2>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle-foreground" />
                <Input
                  aria-label="Search enquiries"
                  placeholder="Search client, product…"
                  className="pl-8 sm:w-56"
                  inputSize="sm"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <div className="overflow-x-auto">
                <Segmented
                  aria-label="Filter by status"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'all', label: `All ${counts.all}` },
                    { value: 'new', label: `Enquiry ${counts.new}` },
                    { value: 'quoted', label: `Quoted ${counts.quoted}` },
                    { value: 'won', label: `Won ${counts.won}` },
                    { value: 'lost', label: `Lost ${counts.lost}` },
                  ]}
                />
              </div>
            </div>
          </div>
          <QueryState
            query={enquiriesQ}
            loading={<DataTable columns={columns} rows={undefined} loading />}
            empty={
              <Card>
                <EmptyState
                  icon={Inbox}
                  title="No enquiries yet"
                  description="Log the first client call or WhatsApp here."
                  action={
                    <Button size="sm" onClick={() => setNewOpen(true)}>
                      <Plus /> New enquiry
                    </Button>
                  }
                />
              </Card>
            }
          >
            {() => (
              <DataTable
                columns={columns}
                rows={rows}
                rowKey={(e) => e.id}
                defaultSort={{ key: 'id', dir: 'desc' }}
                empty={<EmptyState compact title="No enquiries match" description="Try another status or search." />}
              />
            )}
          </QueryState>
        </section>

        <aside className="space-y-6">
          <TargetsCard query={summaryQ} />
          {summary && summary.lost_reasons.length > 0 && <LostReasonsCard reasons={summary.lost_reasons} />}
        </aside>
      </div>

      <NewEnquiryDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        people={people}
        onCreated={(e) => setAdded((a) => [e, ...a])}
      />
      <QuoteDialog
        enquiry={quoteFor}
        onOpenChange={(v) => !v && setQuoteFor(null)}
        onQuoted={(e, q) => {
          save(e)
          setQuotes((m) => ({ ...m, [e.id]: q }))
        }}
      />
      <StatusDialog target={statusFor} onOpenChange={(v) => !v && setStatusFor(null)} onUpdated={save} />
    </>
  )
}

function RowActions({
  e,
  onQuote,
  onStatus,
}: {
  e: Enquiry
  onQuote: () => void
  onStatus: (s: 'won' | 'lost') => void
}) {
  if (e.status === 'new') {
    return (
      <Button size="sm" variant="secondary" onClick={onQuote}>
        Make quote
      </Button>
    )
  }
  if (e.status === 'quoted') {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="secondary">
            Mark won / lost
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => onStatus('won')}>Mark won</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onStatus('lost')}>Mark lost…</DropdownMenuItem>
          <DropdownMenuItem onSelect={onQuote}>Revise quote</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }
  return null
}

function ValidityChip({ validUntil, quoteId }: { validUntil: string; quoteId: string | null }) {
  const days = daysUntil(validUntil)
  const tone: Tone = days < 0 ? 'danger' : days <= 3 ? 'warn' : 'ok'
  const label = days < 0 ? `Expired ${-days} d ago` : days === 0 ? 'Expires today' : `${days} d left`
  const pct = Math.max(0, Math.min(1, days / QUOTE_VALIDITY_DAYS))
  return (
    <div className="flex min-w-32 flex-col gap-1" title={`${quoteId ?? 'Quote'} valid until ${formatDate(validUntil)}`}>
      <Badge tone={tone} size="sm" className="self-start">
        {label}
      </Badge>
      <div className="h-1 w-full overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
        <div
          className={cn('h-full rounded-full', tone === 'ok' ? 'bg-ok' : tone === 'warn' ? 'bg-warn' : 'bg-danger')}
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <span className="text-2xs text-muted-foreground">
        {quoteId} · till {formatDate(validUntil)}
      </span>
    </div>
  )
}

function ProgressBar({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'ok' | 'warn' }) {
  const pct = Math.max(0, Math.min(1, value))
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
      <div
        className={cn('h-full rounded-full', tone === 'ok' ? 'bg-ok' : tone === 'warn' ? 'bg-warn' : 'bg-accent')}
        style={{ width: `${pct * 100}%` }}
      />
    </div>
  )
}

function TargetsCard({ query }: { query: UseApiResult<MarketingSummary> }) {
  return (
    <Card>
      <CardHeader
        title="Targets vs achieved"
        description={query.data ? `Sales booked in ${formatMonth(query.data.month)}` : 'This month'}
      />
      <CardContent>
        <QueryState
          query={query}
          loading={
            <div className="space-y-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="space-y-2">
                  <Skeleton className="h-3.5 w-32" />
                  <Skeleton className="h-2 w-full" />
                </div>
              ))}
            </div>
          }
          empty={<EmptyState compact title="No targets set" description="Targets appear once the owner sets them." />}
        >
          {(s) => {
            const behind = s.achievement_pct < 0.75
            return (
              <div className="space-y-5">
                <div className="space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="tabular text-2xl font-semibold text-foreground">{formatINRShort(s.achieved)}</span>
                    <span className="text-sm text-muted-foreground">of {formatINRShort(s.target)}</span>
                  </div>
                  <ProgressBar value={s.achievement_pct} tone={behind ? 'warn' : 'ok'} />
                  <p className="text-xs text-muted-foreground">
                    {formatPercent(s.achievement_pct)} achieved · {formatINRShort(s.pipeline_value)} in open quotes
                  </p>
                </div>
                <ul className="space-y-4 border-t border-border pt-4">
                  {s.by_person.map((p) => {
                    const pct = p.target ? p.achieved / p.target : 0
                    return (
                      <li key={p.name} className="space-y-1.5">
                        <div className="flex items-baseline justify-between gap-2 text-sm">
                          <span className="font-medium text-foreground">{p.name}</span>
                          <span className="tabular text-muted-foreground">{formatPercent(pct, { digits: 0 })}</span>
                        </div>
                        <ProgressBar value={pct} />
                        <div className="flex justify-between gap-2 text-xs text-muted-foreground">
                          <span className="tabular">
                            {formatINRShort(p.achieved)} / {formatINRShort(p.target)}
                          </span>
                          <span>
                            {p.won} won of {p.enquiries}
                          </span>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )
          }}
        </QueryState>
      </CardContent>
    </Card>
  )
}

function LostReasonsCard({ reasons }: { reasons: { reason: string; count: number }[] }) {
  const max = Math.max(...reasons.map((r) => r.count), 1)
  return (
    <Card>
      <CardHeader title="Why we lose" description="Lost enquiries by reason" />
      <CardContent>
        <ul className="space-y-3">
          {reasons.map((r) => (
            <li key={r.reason} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm">
              <span className="truncate text-foreground">{r.reason}</span>
              <span className="tabular text-muted-foreground">{r.count}</span>
              <div className="col-span-2 h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                <div className="h-full rounded-full bg-danger/70" style={{ width: `${(r.count / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
