import type { Job } from '@contract/types'
import type { Tone } from '@/components/ui'

export const JOB_STATUS_LABEL: Record<Job['status'], string> = {
  planned: 'Planned',
  design: 'Design',
  printing: 'Printing',
  qc: 'QC',
  dispatch: 'Dispatch',
  invoiced: 'Invoiced',
  closed: 'Closed',
  hold: 'On hold',
}

export const JOB_STATUS_TONE: Record<Job['status'], Tone> = {
  planned: 'info',
  design: 'accent',
  printing: 'accent',
  qc: 'warn',
  dispatch: 'warn',
  invoiced: 'ok',
  closed: 'neutral',
  hold: 'danger',
}

export const FLAG_LABEL: Record<Job['flags'][number], string> = {
  wastage_high: 'High wastage',
  material_variance: 'Material variance',
  overprod: 'Over-production',
  material_short: 'Paper short',
  client_locked: 'Client locked',
  qc_hold: 'QC hold',
  late: 'Late',
}

/** List endpoint may return `{ total, items }` or a bare array. */
export function jobItems(data: unknown): Job[] {
  if (Array.isArray(data)) return data as Job[]
  if (data && typeof data === 'object' && Array.isArray((data as { items?: unknown }).items)) {
    return (data as { items: Job[] }).items
  }
  return []
}
