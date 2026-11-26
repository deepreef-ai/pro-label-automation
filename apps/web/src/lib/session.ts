import { useSyncExternalStore } from 'react'
import { ROLES, ROLE_LABELS, setRole, type Role } from './role'
import { safeStorage } from './utils'

/*
 * Multi-tenant session (demo v0.2, task W1 #56).
 *
 * One app serves many label companies. After sign-in the session holds the company and the role from
 * the login token; the backend takes the company ONLY from that token (never from the URL or a field
 * the user can edit). Without a session the app behaves like demo v0.1 (Pro Labels, role switcher),
 * unless VITE_REQUIRE_LOGIN=true, which sends every visitor to /login first.
 *
 * Until the K1 contract (#49) adds the login fixtures, sign-in in mock mode (and in live mode while the
 * backend has no /api/auth/login) uses the demo directory below: synthetic companies and logins only.
 */

export interface Company {
  id: string
  name: string
  /** Web address prefix: `<slug>.ourapp.in`. */
  slug: string
}

export type SessionRole = Role | 'platform_admin'

export interface Session {
  token: string
  company: Company
  user: { name: string; login: string }
  role: SessionRole
}

/** Shape returned by POST /api/auth/login (contract §6.2, K1 #49): the role is inside `user`. */
export interface LoginResponse {
  token?: string
  token_type?: string
  expires_at?: string
  company?: Company | null
  user?: { id?: string; name: string; login: string; role?: SessionRole }
  role?: SessionRole
}

export const REQUIRE_LOGIN = import.meta.env.VITE_REQUIRE_LOGIN === 'true'
export const APP_DOMAIN = 'ourapp.in'
export const DEMO_OTP = '123456'

/** Company shown when nobody is signed in (demo v0.1 behaviour). */
export const DEFAULT_COMPANY: Company = {
  id: 'CO-001',
  name: 'Pro Labels',
  slug: 'prolabels',
}

/* ------------------------------------------------------------------ */
/* Demo directory: synthetic companies and logins (no real people)     */
/* ------------------------------------------------------------------ */

/** Platform staff sign in at `platform.ourapp.in`; they have no company (contract: `company: null`). */
export const PLATFORM_COMPANY: Company = { id: 'PLATFORM', name: 'Label AI Ops', slug: 'platform' }

export const DEMO_COMPANIES: Company[] = [
  DEFAULT_COMPANY,
  { id: 'CO-002', name: 'Sunrise Flexo Prints', slug: 'sunriseflexo' },
  { id: 'CO-003', name: 'Nilgiri Label Works', slug: 'nilgirilabels' },
]

export interface DemoLogin {
  company: Company
  /** The real demo user the backend knows (contract fixtures + core/etl/tenants.py; G1 prints them). */
  login: string
  role: SessionRole
}

const [PRO, SUN, NIL] = DEMO_COMPANIES

/**
 * Demo users, exactly as seeded in the backend (made-up people; OTP is always DEMO_OTP), so the same logins
 * work in mock and live mode. The platform admin has no company: the backend expects an empty company address.
 */
export const DEMO_LOGINS: DemoLogin[] = [
  { company: PRO, login: '+91 90000 00001', role: 'owner' },
  { company: PRO, login: '+91 90000 00003', role: 'ppic' },
  { company: PRO, login: 'kavita@prolabels.example', role: 'design' },
  { company: PRO, login: '+91 90000 00005', role: 'store' },
  { company: PRO, login: '+91 90000 00006', role: 'production' },
  { company: PRO, login: '+91 90000 00007', role: 'qc' },
  { company: PRO, login: '+91 90000 00008', role: 'dispatch' },
  { company: PRO, login: 'neha@prolabels.example', role: 'accounts' },
  { company: SUN, login: '+91 90000 00201', role: 'owner' },
  { company: SUN, login: '+91 90000 00202', role: 'store' },
  { company: SUN, login: '+91 90000 00204', role: 'production' },
  { company: SUN, login: 'swati@sunriseflexo.example', role: 'accounts' },
  { company: NIL, login: '+91 90000 00301', role: 'owner' },
  { company: NIL, login: 'lakshmi@nilgirilabels.example', role: 'accounts' },
  { company: PLATFORM_COMPANY, login: 'admin@platform.example', role: 'platform_admin' },
]

/** Same login, ignoring spaces and case (`+91 90000 00201` = `+919000000201`). */
function sameLogin(a: string, b: string): boolean {
  const norm = (s: string) => s.replace(/\s+/g, '').toLowerCase()
  return norm(a) === norm(b)
}

/** Mock-mode shortcuts kept from the first build: `<role>@<company>.demo` and `admin@platform.demo`. */
function aliasRole(company: Company, login: string): SessionRole | null {
  const id = login.trim().toLowerCase()
  if (company.slug === PLATFORM_COMPANY.slug) return id === 'admin@platform.demo' ? 'platform_admin' : null
  const m = /^([a-z]+)@([a-z0-9-]+)\.demo$/.exec(id)
  return m && m[2] === company.slug && (ROLES as readonly string[]).includes(m[1]) ? (m[1] as Role) : null
}

/** Company address the backend expects: platform staff sign in with no company (contract §6.2). */
export function backendSlug(input: string): string {
  const s = normaliseSlug(input)
  return s === PLATFORM_COMPANY.slug ? '' : s
}

export function companyBySlug(slug: string): Company | undefined {
  const s = normaliseSlug(slug)
  return [...DEMO_COMPANIES, PLATFORM_COMPANY].find((c) => c.slug === s)
}

export function roleLabel(role: SessionRole): string {
  return roleTitle(role)
}

/** Accepts `sunrise`, `sunrise.ourapp.in` or `https://sunrise.ourapp.in/`. */
export function normaliseSlug(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/\/.*$/, '')
    .replace(new RegExp(`\\.${APP_DOMAIN.replace('.', '\\.')}$`), '')
}

export class LoginError extends Error {
  constructor(
    message: string,
    readonly field: 'company' | 'login' | 'otp',
  ) {
    super(message)
    this.name = 'LoginError'
  }
}

/** Demo sign-in against the local directory. Throws LoginError with the field to highlight. */
export function demoSignIn(companySlug: string, login: string, otp: string): Session {
  const company = companyBySlug(companySlug)
  if (!company)
    throw new LoginError(
      `We don't know "${normaliseSlug(companySlug) || companySlug}". Check your company web address.`,
      'company',
    )
  const alias = aliasRole(company, login)
  const user: DemoLogin | undefined =
    DEMO_LOGINS.find((d) => d.company.slug === company.slug && sameLogin(d.login, login)) ??
    (alias ? { company, login: login.trim().toLowerCase(), role: alias } : undefined)
  if (!user) throw new LoginError(`No user "${login.trim()}" in ${company.name}.`, 'login')
  if (otp.trim() !== DEMO_OTP) throw new LoginError('Wrong OTP. Please check the code and try again.', 'otp')
  return {
    token: `demo.${company.id}.${user.role}`,
    company,
    user: {
      name: `${roleTitle(user.role)} (${company.name})`,
      login: user.login,
    },
    role: user.role,
  }
}

function roleTitle(role: SessionRole): string {
  return role === 'platform_admin' ? 'Platform admin' : ROLE_LABELS[role]
}

/** Turns a backend login response into a session; null when it is not a real login answer (mock echo). */
export function sessionFromResponse(res: LoginResponse | undefined): Session | null {
  const role = res?.user?.role ?? res?.role
  if (!res?.token || !role) return null
  // Platform staff have no company (contract: `company: null`); company users always have one.
  const company = res.company?.id ? res.company : role === 'platform_admin' ? PLATFORM_COMPANY : null
  if (!company) return null
  return {
    token: res.token,
    company,
    user: { name: res.user?.name ?? roleTitle(role), login: res.user?.login ?? '' },
    role,
  }
}

/* ------------------------------------------------------------------ */
/* Store                                                               */
/* ------------------------------------------------------------------ */

const KEY = 'pl.session'
const LAST_COMPANY_KEY = 'pl.lastCompany'
const listeners = new Set<() => void>()

function read(): Session | null {
  const raw = safeStorage.get(KEY)
  if (!raw) return null
  try {
    const s = JSON.parse(raw) as Session
    return s?.token && s.company?.id ? s : null
  } catch {
    return null
  }
}

let current: Session | null = read()

export function getSession(): Session | null {
  return current
}

export function getToken(): string | null {
  return current?.token ?? null
}

/** Company in view: the signed-in company, else the demo default. */
export function currentCompany(): Company {
  return current?.company ?? DEFAULT_COMPANY
}

export function lastCompanySlug(): string {
  return safeStorage.get(LAST_COMPANY_KEY) || DEFAULT_COMPANY.slug
}

export function signIn(session: Session): void {
  current = session
  safeStorage.set(KEY, JSON.stringify(session))
  safeStorage.set(LAST_COMPANY_KEY, session.company.slug)
  if ((ROLES as readonly string[]).includes(session.role)) setRole(session.role as Role)
  listeners.forEach((l) => l())
}

export function signOut(): void {
  current = null
  safeStorage.set(KEY, '')
  setRole('owner')
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** Current session (null = not signed in); re-renders on sign-in / sign-out. */
export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, getSession, getSession)
}

export function initials(name: string): string {
  return name.trim().charAt(0).toUpperCase() || '?'
}
