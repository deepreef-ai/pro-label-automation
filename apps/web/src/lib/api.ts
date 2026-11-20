/**
 * The one API client (SPEC §5).
 *
 *   VITE_API_MODE=mock (default)  -> answers come from contract/fixtures via fixtures/index.json
 *   VITE_API_MODE=live            -> fetch(VITE_API_URL + path) with the X-Role header
 *
 * Usage:
 *   const jobs = await api.get<Job[]>('/api/jobs?status=open')
 *   const { data, loading, error, noData, refetch } = useApi<Job[]>('/api/jobs')
 */
import { useCallback, useEffect, useState } from 'react'
import { getRole, useRole } from './role'
import { sleep } from './utils'

export type ApiMode = 'mock' | 'live'

export const API_MODE: ApiMode = import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock'
export const API_URL: string = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '') || 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number
  /** True when mock mode has no fixture for this call (show "No data yet", not an error). */
  readonly missingFixture: boolean
  readonly body: unknown

  constructor(status: number, message: string, opts: { missingFixture?: boolean; body?: unknown } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.missingFixture = opts.missingFixture ?? false
    this.body = opts.body
  }
}

/** True for "nothing here yet" (missing fixture or 404) rather than a real failure. */
export function isNoData(err: unknown): boolean {
  return err instanceof ApiError && (err.missingFixture || err.status === 404)
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

/* ------------------------------------------------------------------ */
/* Mock mode                                                           */
/* ------------------------------------------------------------------ */

// Every JSON file in contract/fixtures, loaded lazily (one small chunk per fixture).
const fixtureModules = import.meta.glob<unknown>('@contract/fixtures/*.json', { import: 'default' })

const byBasename = new Map<string, () => Promise<unknown>>()
for (const [p, loader] of Object.entries(fixtureModules)) {
  byBasename.set(p.split('/').pop()!.toLowerCase(), loader)
}

interface MockRoute {
  method: string
  /** Path segments of the key, e.g. ['api','jobs','{job_card}'] */
  segments: string[]
  /** Normalised query string of the key ('' if none) */
  query: string
  file?: string
  inline?: unknown
  hasInline: boolean
}

function normaliseQuery(q: string): string {
  if (!q) return ''
  const pairs: [string, string][] = []
  new URLSearchParams(q).forEach((v, k) => pairs.push([k, v]))
  pairs.sort(([a, av], [b, bv]) => (a === b ? av.localeCompare(bv) : a.localeCompare(b)))
  return pairs.map(([k, v]) => `${k}=${v}`).join('&')
}

function splitPath(path: string): { segments: string[]; query: string } {
  const i = path.indexOf('?')
  const p = i === -1 ? path : path.slice(0, i)
  const q = i === -1 ? '' : path.slice(i + 1)
  return { segments: p.split('/').filter(Boolean), query: normaliseQuery(q) }
}

const METHOD_KEY = /^\s*(GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s*$/i

function toRoute(key: string, value: unknown): MockRoute | null {
  const m = METHOD_KEY.exec(key)
  if (!m) return null
  const { segments, query } = splitPath(m[2])
  let file: string | undefined
  let inline: unknown
  let hasInline = false
  if (typeof value === 'string') file = value
  else if (value && typeof value === 'object' && !Array.isArray(value)) {
    const v = value as Record<string, unknown>
    const f = v.file ?? v.fixture ?? v.response_file
    if (typeof f === 'string') file = f
    else if ('data' in v || 'body' in v || 'response' in v) {
      inline = v.data ?? v.body ?? v.response
      hasInline = true
    }
  }
  if (file) file = file.split(/[\\/]/).pop()!.toLowerCase()
  if (!file && !hasInline) return null
  return { method: m[1].toUpperCase(), segments, query, file, inline, hasInline }
}

let routesPromise: Promise<MockRoute[]> | null = null

/** Reads contract/fixtures/index.json once. Accepts several shapes:
 *  { "GET /api/x": "x.json" } | { "GET /api/x": { "file": "x.json" } } | { routes: {...} } | [{ method, path, file }]
 */
function loadRoutes(): Promise<MockRoute[]> {
  if (routesPromise) return routesPromise
  routesPromise = (async () => {
    const loader = byBasename.get('index.json')
    if (!loader) return []
    const index = await loader()
    const routes: MockRoute[] = []
    const add = (k: string, v: unknown) => {
      const r = toRoute(k, v)
      if (r) routes.push(r)
    }
    const visit = (node: unknown) => {
      if (Array.isArray(node)) {
        for (const e of node) {
          if (e && typeof e === 'object') {
            const o = e as Record<string, unknown>
            const key = typeof o.key === 'string' ? o.key : `${String(o.method ?? 'GET')} ${String(o.path ?? '')}`
            add(key, o)
          }
        }
      } else if (node && typeof node === 'object') {
        for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
          if (METHOD_KEY.test(k)) add(k, v)
          else if (typeof v === 'object') visit(v)
        }
      }
    }
    visit(index)
    return routes
  })()
  return routesPromise
}

/** Score (higher = better) or -1 when the route does not match. Literal segments beat {params};
 *  an exact query variant beats the plain key, which is the fallback for any query. */
function matchScore(route: MockRoute, method: string, segments: string[], query: string): number {
  if (route.method !== method || route.segments.length !== segments.length) return -1
  let literal = 0
  for (let i = 0; i < segments.length; i++) {
    const rs = route.segments[i]
    if (/^\{.+\}$/.test(rs) || rs.startsWith(':')) continue
    if (safeDecode(rs) !== safeDecode(segments[i])) return -1
    literal++
  }
  if (route.query) return route.query === query ? literal * 10 + 5 : -1
  return literal * 10
}

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

async function resolveFixture(method: Method, path: string): Promise<{ found: boolean; data?: unknown }> {
  const routes = await loadRoutes()
  const { segments, query } = splitPath(path)
  let best: MockRoute | null = null
  let bestScore = -1
  for (const r of routes) {
    const s = matchScore(r, method, segments, query)
    if (s > bestScore) {
      best = r
      bestScore = s
    }
  }
  if (!best) return { found: false }
  if (best.hasInline) return { found: true, data: structuredClone(best.inline) }
  const loader = best.file ? byBasename.get(best.file) : undefined
  if (!loader) return { found: false }
  return { found: true, data: structuredClone(await loader()) }
}

async function mockRequest<T>(method: Method, path: string, body?: unknown): Promise<T> {
  await sleep(150 + Math.random() * 150)
  const hit = await resolveFixture(method, path)
  if (hit.found) return hit.data as T
  if (method === 'GET') {
    throw new ApiError(404, `No demo data yet for ${method} ${path}`, { missingFixture: true })
  }
  const echo = body && typeof body === 'object' && !(body instanceof FormData) ? body : {}
  return { ok: true, ...echo } as T
}

/* ------------------------------------------------------------------ */
/* Live mode                                                           */
/* ------------------------------------------------------------------ */

async function liveRequest<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { 'X-Role': getRole(), Accept: 'application/json' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: payload, signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'Cannot reach the server. Is the API running?')
  }
  const text = await res.text()
  let data: unknown = undefined
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data ? String((data as { detail: unknown }).detail) : res.statusText
    throw new ApiError(res.status, detail || `Request failed (${res.status})`, { body: data })
  }
  return data as T
}

/* ------------------------------------------------------------------ */
/* Public client                                                       */
/* ------------------------------------------------------------------ */

function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return API_MODE === 'live' ? liveRequest<T>(method, path, body, signal) : mockRequest<T>(method, path, body)
}

export const api = {
  mode: API_MODE,
  get: <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

/** Build a path with query params, skipping empty values: withQuery('/api/jobs', { status: 'open', q: '' }) */
export function withQuery(path: string, params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `${path}?${s}` : path
}

export interface UseApiResult<T> {
  data: T | undefined
  error: Error | undefined
  loading: boolean
  /** True when there is simply no data (missing fixture / 404): show an EmptyState, not an error. */
  noData: boolean
  refetch: () => void
}

interface ApiState<T> {
  key: string | null
  data?: T
  error?: Error
  loading: boolean
}

/**
 * Fetch `path` on mount and whenever it (or the role) changes. Pass `null` to skip.
 * Keeps the previous data while refetching so screens don't flash.
 */
export function useApi<T>(path: string | null): UseApiResult<T> {
  const role = useRole()
  const [tick, setTick] = useState(0)
  const [state, setState] = useState<ApiState<T>>({ key: null, loading: path !== null })

  useEffect(() => {
    if (path === null) return
    const ctrl = new AbortController()
    let active = true
    setState((s) => ({ key: path, data: s.data, loading: true }))
    api
      .get<T>(path, ctrl.signal)
      .then((data) => {
        if (active) setState({ key: path, data, loading: false })
      })
      .catch((error: unknown) => {
        if (!active || (error as Error)?.name === 'AbortError') return
        setState({ key: path, error: error instanceof Error ? error : new Error(String(error)), loading: false })
      })
    return () => {
      active = false
      ctrl.abort()
    }
  }, [path, tick, role])

  const refetch = useCallback(() => setTick((t) => t + 1), [])

  if (path === null) return { data: undefined, error: undefined, loading: false, noData: false, refetch }
  return {
    data: state.data,
    error: state.error,
    loading: state.loading || state.key !== path,
    noData: isNoData(state.error),
    refetch,
  }
}
