import { Construction } from 'lucide-react'
import { EmptyState, PageHeader } from '@/components/ui'

/** Placeholder: replaced by task W3 (only this folder changes). */
export default function Page() {
  return (
    <>
      <PageHeader title="Job 360" subtitle="Coming in task W3" />
      <EmptyState icon={Construction} title="This screen is being built" description="Task W3 replaces this placeholder." />
    </>
  )
}
