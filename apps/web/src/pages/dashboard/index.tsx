import { Construction } from 'lucide-react'
import { EmptyState, PageHeader } from '@/components/ui'

/** Placeholder: replaced by task W2 (only this folder changes). */
export default function Page() {
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Coming in task W2" />
      <EmptyState icon={Construction} title="This screen is being built" description="Task W2 replaces this placeholder." />
    </>
  )
}
