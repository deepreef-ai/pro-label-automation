import { useSearchParams } from 'react-router-dom'
import { PageHeader, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { OverviewTab } from './overview'
import { InvoicesTab } from './invoices'
import { DebtorsTab } from './debtors'
import { CollectionsTab } from './collections'
import { CreditorsTab } from './creditors'
import { CashPlanTab } from './cashplan'
import { PnlTab } from './pnl'

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'invoices', label: 'Invoices' },
  { value: 'debtors', label: 'Debtors' },
  { value: 'collections', label: 'Collections' },
  { value: 'creditors', label: 'Creditors' },
  { value: 'cashplan', label: 'Cash plan' },
  { value: 'pnl', label: 'P&L' },
] as const

export default function MoneyPage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const tab = TABS.some((t) => t.value === raw) ? (raw as string) : 'overview'

  const go = (next: string) => {
    setParams(next === 'overview' ? {} : { tab: next }, { replace: true })
  }

  return (
    <div>
      <PageHeader
        title="Money"
        subtitle="What clients owe, what we owe suppliers, cash for the next six months, and profit checked against Tally."
      />
      <Tabs value={tab} onValueChange={go}>
        <TabsList aria-label="Money sections">
          {TABS.map((t) => (
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
