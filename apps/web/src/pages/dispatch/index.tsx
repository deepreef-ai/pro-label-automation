import { Construction } from 'lucide-react'
import { EmptyState, PageHeader } from '@/components/ui'

/** Placeholder: replaced by task W4 (only this folder changes). */
export default function Page() {
  return (
    <>
      <PageHeader title="Dispatch" subtitle="Coming in task W4" />
      <EmptyState icon={Construction} title="This screen is being built" description="Task W4 replaces this placeholder." />
    </>
  )
}
