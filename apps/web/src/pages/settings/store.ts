/**
 * Mock-mode settings store (module level, in memory; resets on page reload).
 *
 * In mock mode `PUT /api/settings` only echoes a fixed fixture, so the Settings page keeps the
 * owner's edits here instead. The Dashboard reads it to re-derive wastage alerts client-side
 * (demo script: "lower wastage tolerance 15% -> 10% and new alerts appear").
 * In live mode this store stays empty and the backend is the source of truth.
 */
import { useSyncExternalStore } from 'react'
import type { Settings } from '@contract/types'

/** SPEC §2 defaults. The alerts fixture was computed with these. */
export const SETTINGS_DEFAULTS = {
  wastage_tol: 0.15,
  overprod_tol: 0.1,
  material_tol: 0.03,
  ink_tol: 0.2,
  slit_tol: 0.05,
  grn_rate_tol: 0.05,
  grace_days: 15,
  msme_days: 45,
  gst_rate: 0.18,
  planning_extra: 0.1,
  admin_pct: 0.05,
  ai_mode: 'cloud',
} as const satisfies Partial<Settings>

let current: Settings | null = null
const listeners = new Set<() => void>()

export function getMockSettings(): Settings | null {
  return current
}

export function setMockSettings(next: Settings): void {
  current = next
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** Settings saved in this session (mock mode), or null if none were saved yet. */
export function useMockSettings(): Settings | null {
  return useSyncExternalStore(subscribe, getMockSettings, getMockSettings)
}
