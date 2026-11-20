import { Construction } from 'lucide-react'
import { EmptyState, PageHeader } from '@/components/ui'

/** Placeholder: replaced by task W5 (only this folder changes). */
export default function Page() {
  return (
    <>
      <PageHeader title="Floor Board" subtitle="Coming in task W5" />
      <EmptyState icon={Construction} title="This screen is being built" description="Task W5 replaces this placeholder." />
    </>
  )
}
