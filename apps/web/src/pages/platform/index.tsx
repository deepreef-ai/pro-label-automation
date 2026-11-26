import { useNavigate } from 'react-router-dom'
import { Building2, IndianRupee, Plus, ShieldCheck, Users } from 'lucide-react'
import type { Company, CompanyList } from '@contract/types'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  DataTable,
  KpiCard,
  PageHeader,
  QueryState,
  toast,
  type Column,
} from '@/components/ui'
import { useApi } from '@/lib/api'
import { formatINRWhole, formatPercent, formatRelative } from '@/lib/format'
import { APP_DOMAIN } from '@/lib/session'
import { BudgetBar, CompanyAvatar, CompanyStatusChip, PlatformOnly } from './shared'

/** Screen 17 · Platform: Companies (W2 #57). */
export default function CompaniesPage() {
  return (
    <PlatformOnly>
      <Companies />
    </PlatformOnly>
  )
}

function Companies() {
  const navigate = useNavigate()
  const q = useApi<CompanyList>('/api/platform/companies')
  const t = q.data?.totals

  const columns: Column<Company>[] = [
    {
      key: 'name',
      header: 'Company',
      sortValue: (c) => c.name,
      cell: (c) => (
        <div className="flex items-center gap-2.5">
          <CompanyAvatar name={c.name} />
          <div className="min-w-0">
            <div className="truncate font-medium">{c.name}</div>
            <div className="text-xs text-muted-foreground">{[c.city, c.state].filter(Boolean).join(', ') || '—'}</div>
          </div>
        </div>
      ),
    },
    { key: 'slug', header: 'Web address', cell: (c) => <span className="text-sm">{`${c.slug}.${APP_DOMAIN}`}</span> },
    { key: 'status', header: 'Status', sortValue: (c) => c.status, cell: (c) => <CompanyStatusChip status={c.status} /> },
    { key: 'users', header: 'Users', align: 'right', sortValue: (c) => c.users, cell: (c) => c.users },
    {
      key: 'import',
      header: 'Last import',
      sortValue: (c) => c.last_import_at ?? '',
      cell: (c) => (c.last_import_at ? formatRelative(c.last_import_at) : <span className="text-muted-foreground">not yet</span>),
    },
    {
      key: 'ai',
      header: 'AI budget used',
      sortValue: (c) => c.ai_used_pct,
      cell: (c) => (
        <div className="space-y-1">
          <BudgetBar pct={c.ai_used_pct} />
          <div className="text-xs text-muted-foreground">
            {formatINRWhole(c.ai_used_month)} of {formatINRWhole(c.ai_budget_month)} (
            {formatPercent(c.ai_used_pct, { digits: 0 })})
          </div>
        </div>
      ),
    },
    {
      key: 'cost',
      header: 'Cost / month',
      align: 'right',
      sortValue: (c) => c.cost_month,
      cell: (c) => <span className="font-medium tabular">{formatINRWhole(c.cost_month)}</span>,
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      cell: (c) =>
        c.status === 'onboarding' ? (
          <Button size="sm" variant="secondary" onClick={() => navigate(`/platform/add-company?company=${c.id}&step=import`)}>
            Set up
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              toast(
                `Support access to ${c.name} is logged and needs the company's approval (product). Demo: sign in as that company.`,
              )
            }
          >
            Open
          </Button>
        ),
    },
  ]

  const companies = t?.companies ?? 0
  return (
    <div className="space-y-6">
      <PageHeader
        title="Companies"
        subtitle="Every customer company on the platform. Each one is fully separate: own users, settings, files and data."
        actions={
          <Button onClick={() => navigate('/platform/add-company')}>
            <Plus /> Add company
          </Button>
        }
      />
      <QueryState query={q}>
        {() => (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <KpiCard
                label="Companies"
                value={String(companies)}
                icon={Building2}
                footer={`${t?.live ?? 0} live · ${t?.parallel_run ?? 0} parallel run · ${t?.onboarding ?? 0} onboarding`}
              />
              <KpiCard label="Active users" value={String(t?.users ?? 0)} icon={Users} footer="across all companies" />
              <KpiCard
                label="Platform cost this month"
                value={formatINRWhole(t?.cost_month)}
                icon={IndianRupee}
                footer={companies ? `≈ ${formatINRWhole((t?.cost_month ?? 0) / companies)} per company` : undefined}
              />
              <KpiCard
                label="Company isolation"
                value={<span className="text-ok">{q.data?.items.every((c) => c.isolation) ? 'ON' : 'CHECK'}</span>}
                icon={ShieldCheck}
                footer="database blocks cross-company reads"
              />
            </div>
            <Card>
              <DataTable columns={columns} rows={q.data?.items} rowKey={(c) => c.id} defaultSort={{ key: 'name', dir: 'asc' }} />
            </Card>
            <Card>
              <CardHeader title="How companies are kept apart" />
              <CardContent className="text-sm text-muted-foreground">
                Every row carries a company ID, and the company comes only from the login token. The database itself (row-level
                security) returns only the signed-in company&apos;s rows, so even a bug cannot show another company&apos;s data.
                Platform staff see this list and costs, never a company&apos;s jobs, stock or money.
              </CardContent>
            </Card>
          </>
        )}
      </QueryState>
    </div>
  )
}
