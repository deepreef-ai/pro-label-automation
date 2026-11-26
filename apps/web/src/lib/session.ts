import { useSyncExternalStore } from 'react'
import { ROLES, setRole, type Role } from './role'
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

/** Shape returned by POST /api/auth/login (K1 #49). */
export interface LoginResponse {
  token?: string
  company?: Company
  user?: { name: string; login: string }
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

export const DEMO_COMPANIES: Company[] = [
  DEFAULT_COMPANY,
  { id: 'CO-002', name: 'Sunrise Labels', slug: 'sunrise' },
  { id: 'CO-003', name: 'Apex Packaging', slug: 'apex' },
]

const DEMO_ROLES: Record<string, Role[]> = {
  prolabels: ['owner', 'ppic', 'design', 'store', 'production', 'qc', 'dispatch', 'accounts'],
  sunrise: ['owner', 'store', 'production', 'accounts'],
  apex: ['owner', 'store'],
}

export interface DemoLogin {
  company: Company
  login: string
  role: Role
}

/** Every demo login, e.g. `store@prolabels.demo`. OTP is always DEMO_OTP. */
export const DEMO_LOGINS: DemoLogin[] = DEMO_COMPANIES.flatMap((company) =>
  (DEMO_ROLES[company.slug] ?? []).map((role) => ({
    company,
    login: `${role}@${company.slug}.demo`,
    role,
  })),
)

export function companyBySlug(slug: string): Company | undefined {
  const s = normaliseSlug(slug)
  return DEMO_COMPANIES.find((c) => c.slug === s)
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
  return role === 'platform_admin' ? 'Platform admin' : role.charAt(0).toUpperCase() + role.slice(1)
}

/** Turns a backend login response into a session; null when it is not a real login answer (mock echo). */
export function sessionFromResponse(res: LoginResponse | undefined): Session | null {
  if (!res?.token || !res.company?.id || !res.role) return null
  return {
    token: res.token,
    company: res.company,
    user: res.user ?? { name: roleTitle(res.role), login: '' },
    role: res.role,
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
