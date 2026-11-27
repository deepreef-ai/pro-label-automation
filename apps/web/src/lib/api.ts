/**
 * The one API client (SPEC §5).
 *
 *   VITE_API_MODE=mock (default)  -> answers come from contract/fixtures via fixtures/index.json
 *   VITE_API_MODE=live            -> fetch(VITE_API_URL + path) with the X-Role header
 *                                    (an endpoint the backend has not built yet -- 404 "Not Found" for
 *                                    the route, or 405 -- falls back to its mock fixture, marked as
 *                                    sample data: see isSampleData() / useApi().sample)
 *
 * Usage:
 *   const jobs = await api.get<Job[]>('/api/jobs?status=open')
 *   const { data, loading, error, noData, refetch } = useApi<Job[]>('/api/jobs')
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { getRole, useRole } from './role'
import { getToken, signOut } from './session'
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

/** A file (e.g. the challan PDF) fetched with the same sign-in headers as every API call. */
export async function fetchFileUrl(path: string): Promise<string> {
  const headers: Record<string, string> = { 'X-Role': getRole() }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${API_URL}${path}`, { headers })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail
    } catch {
      // not JSON
    }
    throw new Error(detail)
  }
  return URL.createObjectURL(await res.blob())
}

async function liveRequest<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { 'X-Role': getRole(), Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
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
  if (res.status === 401 && token && !path.startsWith('/api/auth/')) {
    // The login token expired or was revoked: sign out and ask the user to sign in again.
    signOut()
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') window.location.assign('/login?expired=1')
  }
  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data ? String((data as { detail: unknown }).detail) : res.statusText
    throw new ApiError(res.status, detail || `Request failed (${res.status})`, { body: data })
  }
  return data as T
}

/* ------------------------------------------------------------------ */
/* Live mode: sample-data fallback for endpoints not built yet          */
/* ------------------------------------------------------------------ */

/** Responses that came from a mock fixture while in live mode (the endpoint is not on the backend yet). */
const sampleResponses = new WeakSet<object>()

/** True when `data` is mock fixture data served in live mode because the backend lacks the endpoint. */
export function isSampleData(data: unknown): boolean {
  return API_MODE === 'live' && typeof data === 'object' && data !== null && sampleResponses.has(data)
}

/**
 * A route the backend does not serve at all: FastAPI answers 404 {"detail":"Not Found"} for an unknown
 * path (a missing record gets a specific detail such as "job JC-9999 not found") and 405 for a path that
 * exists with another method.
 */
function isMissingRoute(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false
  if (err.status === 405) return true
  return err.status === 404 && err.message === 'Not Found'
}

interface LiveRoute {
  method: string
  segments: string[]
}

let liveRoutesPromise: Promise<LiveRoute[] | null> | null = null

/** The backend's routes from its OpenAPI document (read once), so calls to endpoints that are not built
 *  yet go straight to the fixture instead of logging a 404 in the console. null = unknown (just try). */
function loadLiveRoutes(): Promise<LiveRoute[] | null> {
  if (liveRoutesPromise) return liveRoutesPromise
  liveRoutesPromise = (async () => {
    try {
      const res = await fetch(`${API_URL}/openapi.json`, { headers: { Accept: 'application/json' } })
      if (!res.ok) return null
      const doc = (await res.json()) as { paths?: Record<string, Record<string, unknown>> }
      if (!doc.paths) return null
      const out: LiveRoute[] = []
      for (const [p, ops] of Object.entries(doc.paths)) {
        for (const m of Object.keys(ops)) out.push({ method: m.toUpperCase(), segments: splitPath(p).segments })
      }
      return out
    } catch {
      liveRoutesPromise = null // backend not up yet: ask again next time
      return null
    }
  })()
  return liveRoutesPromise
}

function backendServes(routes: LiveRoute[], method: Method, path: string): boolean {
  const { segments } = splitPath(path)
  return routes.some(
    (r) =>
      r.method === method &&
      r.segments.length === segments.length &&
      r.segments.every((rs, i) => /^\{.+\}$/.test(rs) || safeDecode(rs) === safeDecode(segments[i])),
  )
}

/** Live mode: does the backend serve this route? (true when it cannot tell; false in mock mode).
 *  For callers that bypass `api`, e.g. an EventSource stream. */
export async function backendHasRoute(method: Method, path: string): Promise<boolean> {
  if (API_MODE !== 'live') return false
  const routes = await loadLiveRoutes()
  return routes ? backendServes(routes, method, path) : true
}

async function sampleFallback<T>(method: Method, path: string, err: unknown): Promise<T> {
  const hit = await resolveFixture(method, path)
  if (!hit.found) {
    if (method === 'GET') throw new ApiError(404, `No data yet for ${method} ${path}`, { missingFixture: true })
    throw err
  }
  const data = hit.data
  if (typeof data === 'object' && data !== null) sampleResponses.add(data)
  return data as T
}

async function liveWithFallback<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const routes = await loadLiveRoutes()
  if (routes && !backendServes(routes, method, path)) {
    return sampleFallback<T>(method, path, new ApiError(404, 'Not Found'))
  }
  try {
    return await liveRequest<T>(method, path, body, signal)
  } catch (err) {
    if (!isMissingRoute(err)) throw err
    return sampleFallback<T>(method, path, err)
  }
}

/* Which mounted useApi() hooks currently show sample data (drives the shell's "Sample data" pill). */
let sampleCount = 0
const sampleListeners = new Set<() => void>()
function changeSampleCount(delta: number) {
  sampleCount += delta
  sampleListeners.forEach((l) => l())
}
function subscribeSample(l: () => void) {
  sampleListeners.add(l)
  return () => {
    sampleListeners.delete(l)
  }
}

/** True while any data on screen is mock sample data served in live mode. */
export function useSampleDataShown(): boolean {
  return useSyncExternalStore(
    subscribeSample,
    () => sampleCount > 0,
    () => false,
  )
}

/* ------------------------------------------------------------------ */
/* Public client                                                       */
/* ------------------------------------------------------------------ */

function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return API_MODE === 'live' ? liveWithFallback<T>(method, path, body, signal) : mockRequest<T>(method, path, body)
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
  /** Live mode only: the backend lacks this endpoint, so `data` is mock sample data (show a DEMO badge). */
  sample: boolean
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

  const sample = path !== null && isSampleData(state.data)
  useEffect(() => {
    if (!sample) return
    changeSampleCount(1)
    return () => changeSampleCount(-1)
  }, [sample])

  if (path === null) return { data: undefined, error: undefined, loading: false, noData: false, sample: false, refetch }
  return {
    data: state.data,
    error: state.error,
    loading: state.loading || state.key !== path,
    noData: isNoData(state.error),
    sample,
    refetch,
  }
}
