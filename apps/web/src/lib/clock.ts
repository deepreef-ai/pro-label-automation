/**
 * One clock for the whole app. The API runs the demo on its own day (`DEMO_TODAY`, 2026-11-20 for the
 * demo story) and refuses dates after it, so every date a form sends must come from the server's
 * "today", not the laptop's calendar. `initClock()` reads it once from `GET /api/health` (`today`);
 * in mock mode or if the call fails the laptop's date is used.
 */
import { API_MODE, api } from './api'

let serverToday: string | null = null

function localIso(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** `YYYY-MM-DD` of the plant's today (the server's demo day in live mode). */
export function appToday(): string {
  return serverToday ?? localIso(new Date())
}

/** ISO date-time: the plant's today with the current clock time (for run start / end). */
export function appNowIso(): string {
  const now = new Date()
  if (!serverToday) return now.toISOString()
  const [y, m, d] = serverToday.split('-').map(Number)
  const t = new Date(now)
  t.setFullYear(y, m - 1, d)
  return t.toISOString()
}

export async function initClock(): Promise<void> {
  if (API_MODE !== 'live') return
  try {
    const h = await api.get<{ today?: string }>('/api/health')
    if (h?.today && /^\d{4}-\d{2}-\d{2}$/.test(h.today)) serverToday = h.today
  } catch {
    // keep the laptop's date; the API will say so if a date is refused
  }
}
