import { useCallback, useSyncExternalStore } from 'react'
import { safeStorage } from '@/lib/utils'

export type Theme = 'light' | 'dark'

const KEY = 'pl.theme'
const listeners = new Set<() => void>()

function initial(): Theme {
  const saved = safeStorage.get(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

let current: Theme = initial()
apply(current)

function apply(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
}

export function setTheme(t: Theme) {
  current = t
  safeStorage.set(KEY, t)
  apply(t)
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

const get = () => current

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, get, get)
  const toggle = useCallback(() => setTheme(current === 'dark' ? 'light' : 'dark'), [])
  return { theme, setTheme, toggle }
}
