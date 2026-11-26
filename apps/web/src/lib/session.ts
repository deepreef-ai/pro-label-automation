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
  company?: Company
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

const DEMO_ROLES: Record<string, Role[]> = {
  prolabels: ['owner', 'ppic', 'design', 'store', 'production', 'qc', 'dispatch', 'accounts'],
  sunriseflexo: ['owner', 'store', 'production', 'accounts'],
  nilgirilabels: ['owner', 'store'],
}

export interface DemoLogin {
  company: Company
  login: string
  role: SessionRole
}

/** Every demo login, e.g. `store@prolabels.demo`, plus the platform admin. OTP is always DEMO_OTP. */
export const DEMO_LOGINS: DemoLogin[] = [
  ...DEMO_COMPANIES.flatMap((company) =>
    (DEMO_ROLES[company.slug] ?? []).map(
      (role): DemoLogin => ({
        company,
        login: `${role}@${company.slug}.demo`,
        role,
      }),
    ),
  ),
  { company: PLATFORM_COMPANY, login: 'admin@platform.demo', role: 'platform_admin' },
]

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
  const id = login.trim().toLowerCase()
  const user = DEMO_LOGINS.find((d) => d.company.slug === company.slug && d.login === id)
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
  if (!res?.token || !res.company?.id || !role) return null
  return {
    token: res.token,
    company: res.company,
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
