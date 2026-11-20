import { useSearchParams } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { EmptyState, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { OverviewTab } from './overview'
import { InvoicesTab } from './invoices'
import { DebtorsTab } from './debtors'
import { CollectionsTab } from './collections'
import { CreditorsTab } from './creditors'
import { CashPlanTab } from './cashplan'
import { PnlTab } from './pnl'
import { useRole, type Role } from '@/lib/role'

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'invoices', label: 'Invoices' },
  { value: 'debtors', label: 'Debtors' },
  { value: 'collections', label: 'Collections' },
  { value: 'creditors', label: 'Creditors' },
  { value: 'cashplan', label: 'Cash plan' },
  { value: 'pnl', label: 'P&L' },
] as const

/** Tabs each role may open (the API's x-roles: owner and accounts see all of Money; marketing only
 *  debtors and collections). Other roles get a short notice instead of a 403 from every tab. */
const ROLE_TABS: Partial<Record<Role, readonly string[]>> = {
  marketing: ['debtors', 'collections'],
}
const MONEY_ROLES: readonly Role[] = ['owner', 'accounts', 'marketing']

export default function MoneyPage() {
  const role = useRole()
  const [params, setParams] = useSearchParams()
  const allowed = ROLE_TABS[role]
  const tabs = allowed ? TABS.filter((t) => allowed.includes(t.value)) : TABS
  const raw = params.get('tab')
  const tab = tabs.some((t) => t.value === raw) ? (raw as string) : tabs[0].value

  const go = (next: string) => {
    setParams(next === 'overview' ? {} : { tab: next }, { replace: true })
  }

  const header = (
    <PageHeader
      title="Money"
      subtitle="What clients owe, what we owe suppliers, cash for the next six months, and profit checked against Tally."
    />
  )
  if (!MONEY_ROLES.includes(role)) {
    return (
      <div>
        {header}
        <EmptyState
          icon={Lock}
          title="Money is for the owner and accounts"
          description="Switch to the Owner or Accounts role to see invoices, debtors, payables and the cash plan."
        />
      </div>
    )
  }

  return (
    <div>
      {header}
      <Tabs value={tab} onValueChange={go}>
        <TabsList aria-label="Money sections">
          {tabs.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab go={go} />
        </TabsContent>
        <TabsContent value="invoices">
          <InvoicesTab />
        </TabsContent>
        <TabsContent value="debtors">
          <DebtorsTab initialFilter={params.get('filter')} />
        </TabsContent>
        <TabsContent value="collections">
          <CollectionsTab />
        </TabsContent>
        <TabsContent value="creditors">
          <CreditorsTab initialVendor={params.get('vendor')} />
        </TabsContent>
        <TabsContent value="cashplan">
          <CashPlanTab />
        </TabsContent>
        <TabsContent value="pnl">
          <PnlTab initialMonth={params.get('month')} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
