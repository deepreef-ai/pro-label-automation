import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowDown, ArrowUp, BriefcaseBusiness, ChevronsUpDown, FileUp, Lock, Search } from 'lucide-react'
import type { Client, Job, JobListResponse, MaterialSummary } from '@contract/types'
import {
  Badge,
  Button,
  Card,
  DemoBadge,
  EmptyState,
  Input,
  KpiCard,
  PageHeader,
  QueryState,
  Select,
  StatusChip,
  TableSkeleton,
  Tooltip,
} from '@/components/ui'
import { useApi, withQuery } from '@/lib/api'
import { formatDate, formatINR, formatINRShort, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { MaterialPanel } from './MaterialPanel'
import { NewJobFromPoDialog } from './NewJobFromPo'
import { FLAG_LABEL, JOB_STATUS_LABEL, JOB_STATUS_TONE, jobItems } from './shared'
import { appToday } from '@/lib/clock'

const STATUS_OPTIONS = [
  { value: 'all', label: 'All statuses' },
  ...(Object.keys(JOB_STATUS_LABEL) as Job['status'][]).map((s) => ({ value: s, label: JOB_STATUS_LABEL[s] })),
]

const OPEN_STATUSES: Job['status'][] = ['planned', 'design', 'printing', 'qc', 'dispatch', 'hold']

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

type SortKey = 'job_card' | 'client_name' | 'order_qty' | 'po_value' | 'due_date' | 'required_m' | 'status'

export default function JobsPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState('all')
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim())
  const [poOpen, setPoOpen] = useState(false)
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'due_date', dir: 'asc' })

  const jobsQ = useApi<JobListResponse | Job[]>(withQuery('/api/jobs', { status: status === 'all' ? '' : status, q }))
  const allJobsQ = useApi<JobListResponse | Job[]>('/api/jobs')
  const clientsQ = useApi<Client[]>('/api/clients')
  const materialQ = useApi<MaterialSummary>('/api/planning/material-summary')

  const lockedClients = useMemo(
    () => new Set((Array.isArray(clientsQ.data) ? clientsQ.data : []).filter((c) => c.lock_status === 'locked').map((c) => c.id)),
    [clientsQ.data],
  )
  const isLocked = (j: Job) => j.flags.includes('client_locked') || lockedClients.has(j.client_id)

  // Filter client-side too, so the screen behaves the same whether or not the server filters.
  const rows = useMemo(() => {
    const needle = q.toLowerCase()
    const list = jobItems(jobsQ.data).filter(
      (j) =>
        (status === 'all' || j.status === status) &&
        (!needle ||
          [j.job_card, j.client_name, j.product, j.po_no, j.material].some((v) => v.toLowerCase().includes(needle))),
    )
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv), 'en-IN', { numeric: true }) * dir
    })
  }, [jobsQ.data, status, q, sort])

  const all = jobItems(allJobsQ.data)
  const open = all.filter((j) => OPEN_STATUSES.includes(j.status))
  const openValue = open.reduce((s, j) => s + j.po_value, 0)
  const today = appToday()
  const late = open.filter((j) => j.due_date < today || j.flags.includes('late')).length
  const lockedCount = all.filter(isLocked).length
  const kpiLoading = allJobsQ.loading && !allJobsQ.data

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle="Job register, paper requirement and shortage check."
        actions={
          <Button onClick={() => setPoOpen(true)}>
            <FileUp /> New job from PO
          </Button>
        }
      />

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Open jobs" icon={BriefcaseBusiness} loading={kpiLoading} value={formatNumber(open.length)} deltaLabel={`${all.length} in register`} />
        <KpiCard label="Open PO value" loading={kpiLoading} value={formatINRShort(openValue)} deltaLabel="not yet invoiced" />
        <KpiCard
          label="Paper shortages"
          icon={AlertTriangle}
          loading={materialQ.loading && !materialQ.data}
          value={formatNumber(materialQ.data?.shortages ?? 0)}
          deltaLabel="paper + width short"
        />
        <KpiCard label="Locked / late" icon={Lock} loading={kpiLoading} value={`${lockedCount} / ${late}`} deltaLabel="client locked · past due" />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section aria-labelledby="register-title" className="min-w-0 space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 id="register-title" className="text-lg font-semibold text-foreground">
              Job register
            </h2>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle-foreground" />
                <Input
                  aria-label="Search jobs"
                  placeholder="Job card, client, PO…"
                  inputSize="sm"
                  className="pl-8 sm:w-60"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <Select aria-label="Filter by status" size="sm" className="sm:w-40" value={status} onValueChange={setStatus} options={STATUS_OPTIONS} />
            </div>
          </div>

          <QueryState
            query={jobsQ}
            loading={
              <Card>
                <TableSkeleton rows={8} columns={7} />
              </Card>
            }
            empty={
              <Card>
                <EmptyState
                  icon={BriefcaseBusiness}
                  title="No jobs yet"
                  description="Create the first job from a client PO."
                  action={
                    <Button size="sm" onClick={() => setPoOpen(true)}>
                      <FileUp /> New job from PO
                    </Button>
                  }
                />
              </Card>
            }
          >
            {() => (
              <div className="overflow-x-auto rounded-lg border border-border bg-surface">
                <table className="w-full min-w-[1080px] border-separate border-spacing-0 text-base">
                  <thead>
                    <tr>
                      <Th sortKey="job_card" sort={sort} onSort={toggleSort}>Job card</Th>
                      <Th sortKey="client_name" sort={sort} onSort={toggleSort}>Client · job</Th>
                      <Th sortKey="order_qty" sort={sort} onSort={toggleSort} right>Qty</Th>
                      <Th right>Rate</Th>
                      <Th sortKey="po_value" sort={sort} onSort={toggleSort} right>PO value</Th>
                      <Th sortKey="status" sort={sort} onSort={toggleSort}>Status</Th>
                      <Th sortKey="due_date" sort={sort} onSort={toggleSort}>Due</Th>
                      <Th sortKey="required_m" sort={sort} onSort={toggleSort} right>Required m</Th>
                      <Th>Lock</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 ? (
                      <tr>
                        <td colSpan={9}>
                          <EmptyState compact title="No jobs match" description="Try another status or search." />
                        </td>
                      </tr>
                    ) : (
                      rows.map((j) => (
                        <JobRow key={j.job_card} job={j} locked={isLocked(j)} today={today} onOpen={() => navigate(`/jobs/${j.job_card}`)} />
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </QueryState>
          <p className="text-xs text-muted-foreground">
            Required m = qty ÷ ups × repeat ÷ 1000. Rows tinted red belong to clients locked for overdue payment.
          </p>
        </section>

        <aside>
          <MaterialPanel query={materialQ} />
        </aside>
      </div>

      <NewJobFromPoDialog open={poOpen} onOpenChange={setPoOpen} />
    </>
  )
}

function Th({
  children,
  sortKey,
  sort,
  onSort,
  right,
}: {
  children: ReactNode
  sortKey?: SortKey
  sort?: { key: SortKey; dir: 'asc' | 'desc' }
  onSort?: (k: SortKey) => void
  right?: boolean
}) {
  const active = sortKey && sort?.key === sortKey
  const Icon = active ? (sort!.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
  return (
    <th
      scope="col"
      aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : undefined}
      className={cn(
        'sticky top-0 border-b border-border bg-surface-muted px-4 py-2.5 text-xs font-medium whitespace-nowrap text-muted-foreground',
        right ? 'text-right' : 'text-left',
      )}
    >
      {sortKey && onSort ? (
        <button
          type="button"
          onClick={() => onSort(sortKey)}
          className={cn('inline-flex items-center gap-1 rounded-sm hover:text-foreground', active && 'text-foreground', right && 'flex-row-reverse')}
        >
          {children}
          <Icon className={cn('size-3', !active && 'opacity-40')} aria-hidden />
        </button>
      ) : (
        children
      )}
    </th>
  )
}

function JobRow({ job: j, locked, today, onOpen }: { job: Job; locked: boolean; today: string; onOpen: () => void }) {
  const open = !['invoiced', 'closed'].includes(j.status)
  const overdue = open && j.due_date < today
  const td = 'border-b border-border px-4 py-3 align-top'
  const otherFlags = j.flags.filter((f) => f !== 'client_locked')
  return (
    <tr
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen()
      }}
      aria-label={`${j.job_card} ${j.client_name}${locked ? ', client locked' : ''}`}
      className={cn(
        'group cursor-pointer transition-colors',
        locked ? 'bg-danger-soft/70 hover:bg-danger-soft' : 'hover:bg-surface-muted',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring',
      )}
    >
      <td className={cn(td, locked && 'border-l-2 border-l-danger')}>
        <div className="flex items-center gap-1.5">
          {locked && <Lock className="size-3.5 text-danger" aria-hidden />}
          <span className="font-medium text-accent group-hover:underline">{j.job_card}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">{j.po_no}</span>
          <DemoBadge show={j.is_demo} />
        </div>
      </td>
      <td className={td}>
        <div className="font-medium text-foreground">{j.client_name}</div>
        <div className="max-w-64 truncate text-xs text-muted-foreground" title={j.product}>
          {j.product} · {j.label_size}
        </div>
      </td>
      <td className={cn(td, 'tabular text-right')}>{formatNumber(j.order_qty)}</td>
      <td className={cn(td, 'tabular text-right text-muted-foreground')}>₹{j.rate.toFixed(2)}</td>
      <td className={cn(td, 'tabular text-right font-medium')}>{formatINR(j.po_value)}</td>
      <td className={td}>
        <div className="flex flex-col items-start gap-1">
          <StatusChip tone={JOB_STATUS_TONE[j.status]}>{JOB_STATUS_LABEL[j.status]}</StatusChip>
          {otherFlags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {otherFlags.map((f) => (
                <Badge key={f} tone={f === 'material_short' || f === 'late' ? 'danger' : 'warn'} size="sm">
                  {FLAG_LABEL[f]}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </td>
      <td className={cn(td, 'whitespace-nowrap', overdue ? 'font-medium text-danger-foreground' : 'text-foreground')}>
        {formatDate(j.due_date)}
        {overdue && <div className="text-xs">overdue</div>}
      </td>
      <td className={cn(td, 'tabular text-right')}>
        <div>{formatNumber(j.required_m)}</div>
        <div className="text-xs text-muted-foreground">plan {formatNumber(j.planned_m)}</div>
      </td>
      <td className={td}>
        {locked ? (
          <Tooltip content="Client has an invoice unpaid beyond due date + grace. Only the owner can release.">
            <span tabIndex={-1}>
              <StatusChip tone="danger">
                <Lock className="size-3" aria-hidden /> Locked
              </StatusChip>
            </span>
          </Tooltip>
        ) : (
          <StatusChip tone="ok" size="sm">
            OK
          </StatusChip>
        )}
      </td>
    </tr>
  )
}
