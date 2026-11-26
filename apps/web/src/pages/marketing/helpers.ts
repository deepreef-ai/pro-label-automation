import type { Enquiry } from '@contract/types'
import type { Tone } from '@/components/ui'
import { parseDate } from '@/lib/format'
import { appToday } from '@/lib/clock'

/** Quotes stay valid for 15 days (client's practice). */
export const QUOTE_VALIDITY_DAYS = 15

export const STATUS_LABEL: Record<Enquiry['status'], string> = {
  new: 'Enquiry',
  quoted: 'Quoted',
  won: 'Won',
  lost: 'Lost',
}

export const STATUS_TONE: Record<Enquiry['status'], Tone> = {
  new: 'info',
  quoted: 'warn',
  won: 'ok',
  lost: 'danger',
}

export const LOST_REASONS = ['Price', 'Delivery date', 'Client on credit hold', 'Quality concern', 'No response', 'Other']

export const SOURCES: Enquiry['source'][] = ['phone', 'email', 'whatsapp', 'visit', 'repeat', 'website']

export function todayISO(): string {
  return appToday() // the server's demo day (see lib/clock)
}

export function toISO(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

export function addDays(iso: string, days: number): string {
  const d = parseDate(iso) ?? new Date()
  d.setDate(d.getDate() + days)
  return toISO(d)
}

/** Whole days from today to `iso` (negative = past). */
export function daysUntil(iso: string): number {
  const d = parseDate(iso)
  const t = parseDate(todayISO())
  if (!d || !t) return 0
  return Math.round((d.getTime() - t.getTime()) / 86_400_000)
}
