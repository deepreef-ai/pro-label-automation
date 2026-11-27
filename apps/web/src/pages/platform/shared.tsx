import type { ReactNode } from 'react'
import { ShieldAlert } from 'lucide-react'
import type { CompanyStatus } from '@contract/types'
import { EmptyState, StatusChip } from '@/components/ui'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'

/** Platform screens (17, 18, 20) are for platform staff; company users get a clear "not for you". */
export function PlatformOnly({ children }: { children: ReactNode }) {
  const session = useSession()
  if (session && session.role !== 'platform_admin') {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Platform admins only"
        description={`You are signed in to ${session.company.name}. Company users see only their own company.`}
      />
    )
  }
  return <>{children}</>
}

const STATUS: Record<CompanyStatus, { label: string; tone: 'ok' | 'warn' | 'info' | 'neutral' }> = {
  live: { label: 'Live', tone: 'ok' },
  parallel_run: { label: 'Parallel run', tone: 'warn' },
  onboarding: { label: 'Onboarding', tone: 'info' },
  paused: { label: 'Paused', tone: 'neutral' },
}

export function CompanyStatusChip({ status }: { status: CompanyStatus }) {
  const s = STATUS[status] ?? { label: status, tone: 'neutral' as const }
  return <StatusChip tone={s.tone}>{s.label}</StatusChip>
}

/** Thin progress bar; turns amber at 80% and red at 100% (AI budget rule, contract §6.4). */
export function BudgetBar({ pct, className }: { pct: number; className?: string }) {
  const p = Math.max(0, Math.min(1, pct))
  return (
    <div className={cn('h-1.5 w-28 overflow-hidden rounded-full bg-surface-sunken', className)} aria-hidden>
      <div
        className={cn('h-full rounded-full', pct >= 1 ? 'bg-danger' : pct >= 0.8 ? 'bg-warn' : 'bg-accent')}
        style={{ width: `${p * 100}%` }}
      />
    </div>
  )
}

export function CompanyAvatar({ name }: { name: string }) {
  return (
    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-bold text-accent-soft-foreground">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  )
}

/** Download rows as a CSV file (fix list). */
export function downloadCsv(fileName: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return
  const cols = Object.keys(rows[0])
  const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}
