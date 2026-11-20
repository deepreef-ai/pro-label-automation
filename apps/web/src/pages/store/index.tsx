import { useSearchParams } from 'react-router-dom'
import { PageHeader, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { OverviewTab } from './overview'
import { ReceiptsTab } from './receipts'
import { IssuesTab } from './issues'
import { InkTab, PartyLaminateTab, RollsTab, SlittingTab, StockTab } from './registers'

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'receipts', label: 'Receipts' },
  { value: 'issues', label: 'Issues' },
  { value: 'stock', label: 'Stock' },
  { value: 'rolls', label: 'Rolls' },
  { value: 'slitting', label: 'Slitting' },
  { value: 'party-laminate', label: 'Party Laminate' },
  { value: 'ink', label: 'Ink Allocation' },
] as const

const ALIASES: Record<string, string> = { grns: 'receipts', 'data-quality': 'overview', items: 'stock' }

export default function StorePage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab') ?? 'overview'
  const tab = ALIASES[raw] ?? (TABS.some((t) => t.value === raw) ? raw : 'overview')

  const openTab = (value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        if (value === 'overview') next.delete('tab')
        else next.set('tab', value)
        next.delete('jc')
        return next
      },
      { replace: true },
    )

  return (
    <div>
      <PageHeader title="Store" subtitle="Live stock, receipts, issues against job cards, rolls, slitting and the monthly ink pool." />
      <Tabs value={tab} onValueChange={openTab}>
        <TabsList aria-label="Store sections">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab onOpenTab={openTab} />
        </TabsContent>
        <TabsContent value="receipts">
          <ReceiptsTab />
        </TabsContent>
        <TabsContent value="issues">
          <IssuesTab initialFilter={params.get('jc') === 'missing' ? 'missing' : 'all'} />
        </TabsContent>
        <TabsContent value="stock">
          <StockTab />
        </TabsContent>
        <TabsContent value="rolls">
          <RollsTab />
        </TabsContent>
        <TabsContent value="slitting">
          <SlittingTab />
        </TabsContent>
        <TabsContent value="party-laminate">
          <PartyLaminateTab />
        </TabsContent>
        <TabsContent value="ink">
          <InkTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
