import type { Design, Die, Plate } from '@contract/types'
import type { Step, Tone } from '@/components/ui'

export type BoardStage = 'artwork' | 'proof_sent' | 'approved' | 'plates_ordered' | 'ready'

export const STEPS: Step[] = [
  { key: 'artwork', label: 'Artwork' },
  { key: 'proof_sent', label: 'Proof sent' },
  { key: 'approved', label: 'Approved' },
  { key: 'plates_ordered', label: 'Plates ordered' },
  { key: 'ready', label: 'Ready' },
]

export function boardStage(s: Design['stage']): BoardStage {
  return s === 'plates_ready' || s === 'done' ? 'ready' : s
}

/** Next stage when the designer moves the job forward. */
export const NEXT_STAGE: Partial<Record<Design['stage'], Design['stage']>> = {
  artwork: 'proof_sent',
  proof_sent: 'approved',
  approved: 'plates_ordered',
  plates_ordered: 'plates_ready',
  plates_ready: 'done',
}

export const STAGE_LABEL: Record<Design['stage'], string> = {
  artwork: 'Artwork',
  proof_sent: 'Proof sent',
  approved: 'Approved',
  plates_ordered: 'Plates ordered',
  plates_ready: 'Plates ready',
  done: 'Ready for press',
}

export const PLATE_TONE: Record<Plate['status'], Tone> = { in_use: 'info', stored: 'ok', damaged: 'danger', scrapped: 'neutral' }
export const PLATE_LABEL: Record<Plate['status'], string> = { in_use: 'In use', stored: 'Stored', damaged: 'Damaged', scrapped: 'Scrapped' }
export const DIE_TONE: Record<Die['status'], Tone> = { ok: 'ok', worn: 'warn', damaged: 'danger', scrapped: 'neutral' }
export const DIE_LABEL: Record<Die['status'], string> = { ok: 'Good', worn: 'Worn', damaged: 'Damaged', scrapped: 'Scrapped' }

export const PRESS_UNITS = 10

export function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object' && Array.isArray((data as { items?: unknown }).items)) return (data as { items: T[] }).items
  return []
}
