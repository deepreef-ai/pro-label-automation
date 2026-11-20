import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Palette, Search } from 'lucide-react'
import type { Design, Die, Plate } from '@contract/types'
import {
  Card,
  type Column,
  DataTable,
  DemoBadge,
  EmptyState,
  Input,
  PageHeader,
  ProgressSteps,
  QueryState,
  Segmented,
  StatusChip,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui'
import { useApi, type UseApiResult } from '@/lib/api'
import { formatDate, formatINR, formatNumber } from '@/lib/format'
import { DesignDrawer } from './DesignDrawer'
import { DIE_LABEL, DIE_TONE, PLATE_LABEL, PLATE_TONE, STAGE_LABEL, STEPS, asList, boardStage } from './shared'

type TabKey = 'jobs' | 'plates' | 'dies'

export default function DesignPage() {
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab')
  const tab: TabKey = tabParam === 'plates' || tabParam === 'dies' ? tabParam : 'jobs'
  const setTab = (t: string) => {
    const p = new URLSearchParams(params)
    if (t === 'jobs') p.delete('tab')
    else p.set('tab', t)
    setParams(p, { replace: true })
  }

  const designQ = useApi<Design[]>('/api/design')
  const platesQ = useApi<Plate[]>('/api/plates')
  const diesQ = useApi<Die[]>('/api/dies')
  const plates = asList<Plate>(platesQ.data)
  const dies = asList<Die>(diesQ.data)

  const [view, setView] = useState<'board' | 'list'>('board')
  const [openJob, setOpenJob] = useState<string | null>(null)
  const [edits, setEdits] = useState<Record<string, Design>>({})
  const designs = useMemo(() => asList<Design>(designQ.data).map((d) => edits[d.job_card] ?? d), [designQ.data, edits])

  return (
    <>
      <PageHeader title="Design" subtitle="Artwork, proofs, approvals, plates and dies." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="jobs">Jobs in design {designs.length > 0 && <span className="text-xs text-muted-foreground">{designs.length}</span>}</TabsTrigger>
          <TabsTrigger value="plates">Plate Store {plates.length > 0 && <span className="text-xs text-muted-foreground">{plates.length}</span>}</TabsTrigger>
          <TabsTrigger value="dies">Die Store {dies.length > 0 && <span className="text-xs text-muted-foreground">{dies.length}</span>}</TabsTrigger>
        </TabsList>

        <TabsContent value="jobs" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">Click a job to see press set-up, colours, route, die and plates.</p>
            <Segmented
              aria-label="View"
              value={view}
              onChange={setView}
              options={[
                { value: 'board', label: 'Board' },
                { value: 'list', label: 'List' },
              ]}
            />
          </div>
          <QueryState
            query={designQ}
            isEmpty={(d) => asList(d).length === 0}
            empty={
              <Card>
                <EmptyState icon={Palette} title="No jobs in design" description="New jobs appear here once PPIC creates them." />
              </Card>
            }
          >
            {() => (view === 'board' ? <Board designs={designs} onOpen={setOpenJob} /> : <DesignList designs={designs} onOpen={setOpenJob} />)}
          </QueryState>
        </TabsContent>

        <TabsContent value="plates">
          <PlateStore query={platesQ} />
        </TabsContent>
        <TabsContent value="dies">
          <DieStore query={diesQ} />
        </TabsContent>
      </Tabs>

      <DesignDrawer
        jobCard={openJob}
        onOpenChange={(v) => !v && setOpenJob(null)}
        plates={plates}
        dies={dies}
        onUpdated={(d) => setEdits((m) => ({ ...m, [d.job_card]: d }))}
      />
    </>
  )
}

function DesignCard({ d, onOpen }: { d: Design; onOpen: (jc: string) => void }) {
  return (
    <Card
      interactive
      role="button"
      tabIndex={0}
      onClick={() => onOpen(d.job_card)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(d.job_card)
        }
      }}
      className="space-y-2 p-3.5"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-accent">{d.job_card}</span>
        <DemoBadge show={d.is_demo} />
      </div>
      <div>
        <p className="truncate text-sm font-medium text-foreground">{d.client_name}</p>
        <p className="truncate text-xs text-muted-foreground" title={d.product}>
          {d.product}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-2xs text-muted-foreground">
        <span>{d.units.length} col</span>
        <span aria-hidden>·</span>
        <span>
          {d.ups_across}×{d.ups_along} ups
        </span>
        <span aria-hidden>·</span>
        <span>v{d.artwork_version}</span>
        {d.die_id && (
          <>
            <span aria-hidden>·</span>
            <span>{d.die_id}</span>
          </>
        )}
      </div>
      <p className="text-2xs text-subtle-foreground">
        {d.designer} · {STAGE_LABEL[d.stage]}
      </p>
    </Card>
  )
}

function Board({ designs, onOpen }: { designs: Design[]; onOpen: (jc: string) => void }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
      {STEPS.map((s, i) => {
        const items = designs.filter((d) => boardStage(d.stage) === s.key)
        return (
          <section key={s.key} aria-label={s.label} className="flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface-muted p-3">
            <header className="flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span className="flex size-5 items-center justify-center rounded-full border border-border-strong bg-surface text-2xs tabular text-muted-foreground">
                  {i + 1}
                </span>
                {s.label}
              </h2>
              <span className="tabular text-xs text-muted-foreground">{items.length}</span>
            </header>
            {items.length ? (
              items.map((d) => <DesignCard key={d.job_card} d={d} onOpen={onOpen} />)
            ) : (
              <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-subtle-foreground">Nothing here</p>
            )}
          </section>
        )
      })}
    </div>
  )
}

function DesignList({ designs, onOpen }: { designs: Design[]; onOpen: (jc: string) => void }) {
  const columns: Column<Design>[] = [
    {
      key: 'job_card',
      header: 'Job',
      cell: (d) => (
        <div>
          <span className="font-medium text-accent">{d.job_card}</span>
          <div className="text-xs text-muted-foreground">{d.client_name}</div>
        </div>
      ),
    },
    {
      key: 'stage',
      header: 'Stage',
      sortValue: (d) => STEPS.findIndex((s) => s.key === boardStage(d.stage)),
      cell: (d) => <ProgressSteps steps={STEPS} current={boardStage(d.stage)} complete={d.stage === 'done'} size="sm" className="min-w-[560px]" />,
    },
    { key: 'designer', header: 'Designer' },
    { key: 'updated_at', header: 'Updated', cell: (d) => formatDate(d.updated_at) },
  ]
  return <DataTable columns={columns} rows={designs} rowKey={(d) => d.job_card} onRowClick={(d) => onOpen(d.job_card)} />
}

function useSearch<T>(rows: T[], fields: (r: T) => (string | null | undefined)[]) {
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const filtered = needle ? rows.filter((r) => fields(r).some((f) => (f ?? '').toLowerCase().includes(needle))) : rows
  return { q, setQ, filtered }
}

function SearchBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="relative mb-3 sm:w-72">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle-foreground" />
      <Input aria-label={label} placeholder={label} inputSize="sm" className="pl-8" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

function PlateStore({ query }: { query: UseApiResult<Plate[]> }) {
  const rows = asList<Plate>(query.data)
  const s = useSearch(rows, (p) => [p.id, p.job_card, p.client_name, p.colour, p.rack])
  const columns: Column<Plate>[] = [
    {
      key: 'id',
      header: 'Plate ID',
      cell: (p) => (
        <span className="flex items-center gap-2">
          <span className="font-mono text-sm font-medium">{p.id}</span>
          <DemoBadge show={p.is_demo} />
        </span>
      ),
    },
    {
      key: 'job_card',
      header: 'Job',
      cell: (p) => (
        <div>
          <Link to={`/jobs/${p.job_card}`} className="rounded-sm font-medium text-accent hover:underline">
            {p.job_card}
          </Link>
          <div className="text-xs text-muted-foreground">{p.client_name}</div>
        </div>
      ),
    },
    { key: 'unit', header: 'Unit · colour', cell: (p) => `${p.unit} · ${p.colour}`, sortValue: (p) => p.unit },
    { key: 'made_on', header: 'Made', cell: (p) => formatDate(p.made_on) },
    { key: 'impressions', header: 'Impressions', align: 'right', cell: (p) => formatNumber(p.impressions) },
    { key: 'cost', header: 'Cost', align: 'right', cell: (p) => formatINR(p.cost) },
    { key: 'rack', header: 'Rack' },
    { key: 'status', header: 'Condition', cell: (p) => <StatusChip tone={PLATE_TONE[p.status]}>{PLATE_LABEL[p.status]}</StatusChip> },
  ]
  return (
    <QueryState query={query} loading={<DataTable columns={columns} rows={undefined} loading />}>
      {() => (
        <>
          <SearchBox value={s.q} onChange={s.setQ} label="Search plate, job, colour, rack…" />
          <DataTable columns={columns} rows={s.filtered} rowKey={(p) => p.id} defaultSort={{ key: 'id', dir: 'desc' }} dense />
          <p className="mt-2 text-xs text-muted-foreground">Plate IDs are permanent and stay with the plate for life.</p>
        </>
      )}
    </QueryState>
  )
}

function DieStore({ query }: { query: UseApiResult<Die[]> }) {
  const rows = asList<Die>(query.data)
  const s = useSearch(rows, (d) => [d.id, d.label_size, d.location, d.last_job_card])
  const columns: Column<Die>[] = [
    {
      key: 'id',
      header: 'Die ID',
      cell: (d) => (
        <span className="flex items-center gap-2">
          <span className="font-mono text-sm font-medium">{d.id}</span>
          <DemoBadge show={d.is_demo} />
        </span>
      ),
    },
    { key: 'type', header: 'Type', cell: (d) => (d.type === 'rotary' ? 'Rotary' : 'Flatbed') },
    { key: 'label_size', header: 'Label size' },
    { key: 'ups', header: 'Ups', sortValue: (d) => d.ups_across * d.ups_along, cell: (d) => `${d.ups_across} × ${d.ups_along}` },
    { key: 'repeat_mm', header: 'Repeat', align: 'right', cell: (d) => `${d.repeat_mm} mm` },
    { key: 'impressions', header: 'Impressions', align: 'right', cell: (d) => formatNumber(d.impressions) },
    {
      key: 'last_job_card',
      header: 'Last job',
      cell: (d) =>
        d.last_job_card ? (
          <Link to={`/jobs/${d.last_job_card}`} className="rounded-sm text-accent hover:underline">
            {d.last_job_card}
          </Link>
        ) : (
          '—'
        ),
    },
    { key: 'location', header: 'Location' },
    { key: 'status', header: 'Condition', cell: (d) => <StatusChip tone={DIE_TONE[d.status]}>{DIE_LABEL[d.status]}</StatusChip> },
  ]
  return (
    <QueryState query={query} loading={<DataTable columns={columns} rows={undefined} loading />}>
      {() => (
        <>
          <SearchBox value={s.q} onChange={s.setQ} label="Search die, size, location…" />
          <DataTable columns={columns} rows={s.filtered} rowKey={(d) => d.id} dense />
        </>
      )}
    </QueryState>
  )
}
