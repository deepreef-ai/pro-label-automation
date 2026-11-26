import { Bot, Building2, IndianRupee, TrendingDown } from 'lucide-react'
import type { CompanyUsage, CostLine, Usage } from '@contract/types'
import { Badge, Card, CardContent, CardHeader, DataTable, KpiCard, PageHeader, QueryState, type Column } from '@/components/ui'
import { useApi } from '@/lib/api'
import { formatINRWhole, formatMonth, formatNumber, formatPercent } from '@/lib/format'
import { BudgetBar, PlatformOnly } from './shared'

/** Screen 20 · Platform: Cost & usage (W2 #57). Udit's target: low cost, falling per company as we grow. */
export default function UsagePage() {
  return (
    <PlatformOnly>
      <UsageScreen />
    </PlatformOnly>
  )
}

const MONTH = '2026-11'

function UsageScreen() {
  const q = useApi<Usage>(`/api/platform/usage?month=${MONTH}`)
  return (
    <div className="space-y-6">
      <PageHeader
        title="Cost & usage"
        subtitle="One shared platform: shared costs are split by active users, per-use costs (AI, OTP) go to the company that used them."
        meta={q.data?.is_estimate ? <Badge tone="warn">Estimate</Badge> : undefined}
      />
      <QueryState query={q}>{(u) => <UsageBody u={u} />}</QueryState>
    </div>
  )
}

function UsageBody({ u }: { u: Usage }) {
  const n = u.companies.length || 1
  const ai = u.companies.reduce((s, c) => s + c.ai_cost, 0)
  const maxLine = Math.max(...u.cost_lines.map((l) => l.monthly), 1)
  const maxGrowth = Math.max(...u.growth.map((g) => g.cost_per_company), 1)
  const one = u.growth.find((g) => g.companies === 1)?.cost_per_company

  const lineCols: Column<CostLine>[] = [
    {
      key: 'label',
      header: 'Item',
      cell: (l) => (
        <div>
          <div className="font-medium">{l.label}</div>
          <div className="text-xs text-muted-foreground">{l.note}</div>
        </div>
      ),
    },
    {
      key: 'basis',
      header: 'Split',
      cell: (l) => (
        <Badge tone={l.basis === 'shared' ? 'neutral' : 'info'}>{l.basis === 'shared' ? 'by active users' : 'per use'}</Badge>
      ),
    },
    {
      key: 'bar',
      header: '',
      width: '30%',
      cell: (l) => (
        <div className="h-2 w-32 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
          <div
            className={l.basis === 'shared' ? 'h-full rounded-full bg-accent' : 'h-full rounded-full bg-info'}
            style={{ width: `${(l.monthly / maxLine) * 100}%` }}
          />
        </div>
      ),
    },
    {
      key: 'monthly',
      header: '₹ / month',
      align: 'right',
      sortValue: (l) => l.monthly,
      cell: (l) => <span className="tabular">{formatINRWhole(l.monthly)}</span>,
    },
  ]

  const coCols: Column<CompanyUsage>[] = [
    { key: 'name', header: 'Company', sortValue: (c) => c.name, cell: (c) => <span className="font-medium">{c.name}</span> },
    { key: 'users', header: 'Users', align: 'right', sortValue: (c) => c.users, cell: (c) => c.users },
    { key: 'saves', header: 'Saves', align: 'right', sortValue: (c) => c.saves, cell: (c) => formatNumber(c.saves) },
    { key: 'pos', header: 'POs read by AI', align: 'right', sortValue: (c) => c.pos_read, cell: (c) => formatNumber(c.pos_read) },
    { key: 'chats', header: 'Chat questions', align: 'right', sortValue: (c) => c.chats, cell: (c) => formatNumber(c.chats) },
    {
      key: 'ai',
      header: 'AI budget',
      sortValue: (c) => c.ai_used_pct,
      cell: (c) => (
        <div className="space-y-1">
          <BudgetBar pct={c.ai_used_pct} />
          <div className="text-xs text-muted-foreground">
            {formatINRWhole(c.ai_cost)} of {formatINRWhole(c.ai_budget_month)}
          </div>
        </div>
      ),
    },
    {
      key: 'shared',
      header: 'Shared',
      align: 'right',
      sortValue: (c) => c.shared_cost,
      cell: (c) => <span className="tabular">{formatINRWhole(c.shared_cost)}</span>,
    },
    {
      key: 'direct',
      header: 'Per use',
      align: 'right',
      sortValue: (c) => c.direct_cost,
      cell: (c) => <span className="tabular">{formatINRWhole(c.direct_cost)}</span>,
    },
    {
      key: 'total',
      header: 'Total',
      align: 'right',
      sortValue: (c) => c.total_cost,
      cell: (c) => <span className="font-semibold tabular">{formatINRWhole(c.total_cost)}</span>,
    },
  ]

  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard
          label={`Total · ${formatMonth(`${u.month}-01`)}`}
          value={formatINRWhole(u.total_cost)}
          icon={IndianRupee}
          footer="all companies, shared platform"
        />
        <KpiCard
          label="Per company"
          value={formatINRWhole(u.total_cost / n)}
          icon={Building2}
          footer={one ? `vs ${formatINRWhole(one)} with 1 company` : `${n} companies`}
        />
        <KpiCard
          label="AI spend"
          value={formatINRWhole(ai)}
          icon={Bot}
          footer={`${formatPercent(ai / (u.total_cost || 1), { digits: 0 })} of total · cached, budget per company`}
        />
        <KpiCard label="Companies on the platform" value={String(n)} icon={TrendingDown} footer="cost per company falls as more join" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <Card>
          <CardHeader title="Where the money goes" description="Monthly cost lines" />
          <DataTable columns={lineCols} rows={u.cost_lines} rowKey={(l) => l.key} dense />
        </Card>
        <Card>
          <CardHeader title="Cost per company as we grow" description="Estimated monthly cost per company" />
          <CardContent>
            <div
              className="flex h-56 items-end gap-3 border-b border-border px-1"
              role="img"
              aria-label="Cost per company falls as companies grow"
            >
              {u.growth.map((g) => (
                <div key={g.companies} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-xs font-semibold tabular">{formatINRWhole(g.cost_per_company)}</span>
                  <div
                    className={g.companies === n ? 'w-full rounded-t-md bg-accent' : 'w-full rounded-t-md bg-accent/45'}
                    style={{ height: `${Math.max(6, (g.cost_per_company / maxGrowth) * 180)}px` }}
                  />
                </div>
              ))}
            </div>
            <div className="mt-1.5 flex gap-3 px-1 text-center text-xs text-muted-foreground">
              {u.growth.map((g) => (
                <div key={g.companies} className="flex-1">
                  {g.companies} {g.companies === 1 ? 'company' : 'cos'}
                  {g.companies === n ? ' (now)' : ''}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Usage by company"
          description="Shared cost split by active users; AI and OTP charged to the company that used them"
        />
        <DataTable columns={coCols} rows={u.companies} rowKey={(c) => c.company_id} defaultSort={{ key: 'total', dir: 'desc' }} />
      </Card>
    </>
  )
}
