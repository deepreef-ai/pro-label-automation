import { useSyncExternalStore } from 'react'
import { safeStorage } from './utils'

/** Demo roles (SPEC §1). Sent to the backend as the `X-Role` header. */
export const ROLES = [
  'owner',
  'ppic',
  'design',
  'store',
  'production',
  'qc',
  'dispatch',
  'accounts',
  'marketing',
] as const

export type Role = (typeof ROLES)[number]

export const ROLE_LABELS: Record<Role, string> = {
  owner: 'Owner',
  ppic: 'PPIC',
  design: 'Design',
  store: 'Store',
  production: 'Production',
  qc: 'QC',
  dispatch: 'Dispatch',
  accounts: 'Accounts',
  marketing: 'Marketing',
}

const KEY = 'pl.role'
const listeners = new Set<() => void>()

function read(): Role {
  const v = safeStorage.get(KEY)
  return (ROLES as readonly string[]).includes(v ?? '') ? (v as Role) : 'owner'
}

let current: Role = read()

export function getRole(): Role {
  return current
}

export function setRole(role: Role): void {
  current = role
  safeStorage.set(KEY, role)
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** Current demo role; re-renders when the role switcher changes it. */
export function useRole(): Role {
  return useSyncExternalStore(subscribe, getRole, getRole)
}
