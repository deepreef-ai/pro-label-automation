import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Building2, ChevronDown, Globe, KeyRound, Lock, ShieldCheck } from 'lucide-react'
import { api } from '@/lib/api'
import { ROLE_LABELS, type Role } from '@/lib/role'
import {
  APP_DOMAIN,
  DEMO_LOGINS,
  DEMO_OTP,
  LoginError,
  REQUIRE_LOGIN,
  companyBySlug,
  demoSignIn,
  initials,
  lastCompanySlug,
  normaliseSlug,
  sessionFromResponse,
  signIn,
  type LoginResponse,
  type Session,
} from '@/lib/session'
import { cn } from '@/lib/utils'
import { Button, Field, Input, toast } from '@/components/ui'

/**
 * Screen 16 · Login (demo v0.2, W1 #56). Each company signs in at its own web address; after sign-in the
 * user sees only that company's data (the backend takes the company from the token, never from this form).
 */

type Step = 'login' | 'otp'
type Err = { field: 'company' | 'login' | 'otp'; message: string } | null

async function signInRequest(company: string, login: string, otp: string): Promise<Session> {
  // Mock mode: the contract fixture always answers the Pro Labels owner, so use the demo directory to try every company.
  if (api.mode === 'mock') return demoSignIn(company, login, otp)
  try {
    const res = await api.post<LoginResponse>('/api/auth/login', {
      company_slug: normaliseSlug(company),
      login: login.trim(),
      otp: otp.trim(),
    })
    const s = sessionFromResponse(res)
    if (s) return s
  } catch (e) {
    // A real 4xx from the backend login wins over the demo directory.
    const status = (e as { status?: number }).status
    if (status === 400 || status === 401 || status === 403) {
      throw new LoginError((e as Error).message || 'Sign-in failed.', 'otp')
    }
  }
  // Mock mode, or a backend without /api/auth/login yet (K1/B1): demo directory.
  return demoSignIn(company, login, otp)
}

export default function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [company, setCompany] = useState(() => params.get('company') || lastCompanySlug())
  const [login, setLogin] = useState('')
  const [otp, setOtp] = useState('')
  const [step, setStep] = useState<Step>('login')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<Err>(null)
  const [resendIn, setResendIn] = useState(0)
  const otpRef = useRef<HTMLInputElement>(null)

  const known = companyBySlug(company)
  const displayName = known?.name ?? 'Your company'
  const expired = params.get('expired') === '1'

  useEffect(() => {
    if (resendIn <= 0) return
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [resendIn])

  useEffect(() => {
    if (step === 'otp') otpRef.current?.focus()
  }, [step])

  function sendOtp(e?: FormEvent) {
    e?.preventDefault()
    setErr(null)
    if (!companyBySlug(company)) {
      setErr({
        field: 'company',
        message: `We don't know "${normaliseSlug(company) || company}". Check your company web address.`,
      })
      return
    }
    if (!login.trim()) {
      setErr({ field: 'login', message: 'Enter your mobile number or email.' })
      return
    }
    setStep('otp')
    setResendIn(30)
    // Contract §6.2: ask the backend to send the OTP (demo mode returns it); errors are ignored, the demo OTP still works.
    if (api.mode === 'live') void api.post('/api/auth/otp', { company_slug: normaliseSlug(company), login: login.trim() }).catch(() => undefined)
    toast(`OTP sent. Demo OTP is ${DEMO_OTP}.`)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (step === 'login') return sendOtp()
    setBusy(true)
    setErr(null)
    try {
      const s = await signInRequest(company, login, otp)
      signIn(s)
      const role = s.role === 'platform_admin' ? 'Platform admin' : ROLE_LABELS[s.role as Role]
      toast.success(`Signed in to ${s.company.name} as ${role}`)
      navigate(params.get('next') || '/', { replace: true })
    } catch (ex) {
      const le = ex instanceof LoginError ? ex : new LoginError('Sign-in failed. Please try again.', 'otp')
      setErr({ field: le.field, message: le.message })
      if (le.field !== 'otp') setStep('login')
    } finally {
      setBusy(false)
    }
  }

  function pickDemo(slug: string, id: string) {
    setCompany(slug)
    setLogin(id)
    setOtp(DEMO_OTP)
    setErr(null)
    setStep('otp')
    setResendIn(0)
  }

  return (
    <div className="flex min-h-screen bg-background">
      {/* Brand panel */}
      <aside className="relative hidden w-[43%] max-w-[620px] flex-col justify-between overflow-hidden bg-gradient-to-br from-accent via-accent-active to-accent-active p-12 text-accent-foreground lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-md bg-accent-foreground font-bold text-accent">
            AI
          </span>
          <span className="text-lg font-semibold">Label AI Ops</span>
        </div>
        <div>
          <h1 className="text-[34px] leading-tight font-bold">
            One live system for
            <br />
            your whole label plant.
          </h1>
          <p className="mt-4 max-w-md text-md opacity-90">
            Jobs, store, press, QC, dispatch and money on one screen. AI drafts; your team approves.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {[
            ['1', 'app for many companies'],
            ['0', 'data shared between companies'],
            ['🔒', 'HTTPS · India (Mumbai)'],
          ].map(([big, small]) => (
            <div key={small} className="rounded-lg bg-white/12 p-3">
              <div className="text-xl font-bold">{big}</div>
              <div className="text-sm opacity-90">{small}</div>
            </div>
          ))}
        </div>
      </aside>

      {/* Form */}
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent-soft px-3 py-1 text-sm font-medium text-accent-soft-foreground">
            <Globe className="size-3.5" aria-hidden />
            {(normaliseSlug(company) || 'yourcompany') + '.' + APP_DOMAIN}
          </div>

          <div className="mb-6 flex items-center gap-3">
            <span className="flex size-11 items-center justify-center rounded-lg bg-accent text-xl font-bold text-accent-foreground">
              {known ? initials(known.name) : <Building2 className="size-5" />}
            </span>
            <div>
              <h2 className="text-xl font-semibold">{displayName}</h2>
              <p className="text-sm text-muted-foreground">Sign in to your company workspace</p>
            </div>
          </div>

          {expired && (
            <p
              role="status"
              className="mb-4 rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn-foreground"
            >
              Your session ended. Please sign in again.
            </p>
          )}

          <form onSubmit={submit} className="space-y-4" noValidate>
            <Field
              label="Company web address"
              htmlFor="company"
              error={err?.field === 'company' ? err.message : undefined}
              hint={`e.g. prolabels.${APP_DOMAIN}`}
            >
              <div className="flex items-center gap-2">
                <Input
                  id="company"
                  value={company}
                  onChange={(e) => {
                    setCompany(e.target.value)
                    setStep('login')
                  }}
                  autoComplete="organization"
                  aria-invalid={err?.field === 'company'}
                  className={cn(err?.field === 'company' && 'border-danger')}
                />
                <span className="shrink-0 text-sm text-muted-foreground">.{APP_DOMAIN}</span>
              </div>
            </Field>

            <Field label="Mobile number or email" htmlFor="login" error={err?.field === 'login' ? err.message : undefined}>
              <Input
                id="login"
                value={login}
                onChange={(e) => {
                  setLogin(e.target.value)
                  setStep('login')
                }}
                placeholder="98XXX XXXXX or name@company.com"
                autoComplete="username"
                aria-invalid={err?.field === 'login'}
                className={cn(err?.field === 'login' && 'border-danger')}
              />
            </Field>

            {step === 'otp' && (
              <Field
                label="One-time password (OTP)"
                htmlFor="otp"
                error={err?.field === 'otp' ? err.message : undefined}
                hint={
                  <span>
                    OTP sent by SMS ·{' '}
                    {resendIn > 0 ? (
                      `resend in 0:${String(resendIn).padStart(2, '0')}`
                    ) : (
                      <button type="button" className="font-medium text-accent hover:underline" onClick={() => sendOtp()}>
                        resend
                      </button>
                    )}
                  </span>
                }
              >
                <Input
                  id="otp"
                  ref={otpRef}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder="● ● ● ● ● ●"
                  aria-invalid={err?.field === 'otp'}
                  className={cn('text-center font-mono text-lg tracking-[0.5em]', err?.field === 'otp' && 'border-danger')}
                />
              </Field>
            )}

            <Button type="submit" size="lg" className="w-full" loading={busy} disabled={step === 'otp' && otp.length < 6}>
              {step === 'login' ? (
                <>
                  <KeyRound /> Send OTP
                </>
              ) : (
                <>
                  <Lock /> Sign in
                </>
              )}
            </Button>
          </form>

          <p className="mt-5 flex gap-2 rounded-md border border-accent/30 bg-accent-soft px-3 py-2.5 text-sm text-accent-soft-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              <b>Your company only.</b> After sign-in you see {displayName} data and nothing else. Your role (e.g. Store) decides
              which screens you get.
            </span>
          </p>

          {!REQUIRE_LOGIN && (
            <Button variant="ghost" size="sm" className="mt-3 w-full" onClick={() => navigate('/')}>
              Continue without signing in (demo)
            </Button>
          )}

          <DemoLogins onPick={pickDemo} />
        </div>
      </main>
    </div>
  )
}

/** Demo helper: click a synthetic login to fill the form (OTP is always DEMO_OTP). */
function DemoLogins({ onPick }: { onPick: (slug: string, login: string) => void }) {
  const [open, setOpen] = useState(false)
  const groups = useMemo(() => {
    const m = new Map<string, typeof DEMO_LOGINS>()
    for (const d of DEMO_LOGINS) m.set(d.company.name, [...(m.get(d.company.name) ?? []), d])
    return [...m.entries()]
  }, [])
  return (
    <div className="mt-6 rounded-lg border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-3 py-2.5 text-sm font-medium"
      >
        Demo logins (OTP {DEMO_OTP})
        <ChevronDown className={cn('size-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-border px-3 py-3">
          {groups.map(([name, list]) => (
            <div key={name}>
              <div className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{name}</div>
              <div className="flex flex-wrap gap-1.5">
                {list.map((d) => (
                  <button
                    key={d.login}
                    type="button"
                    onClick={() => onPick(d.company.slug, d.login)}
                    className="rounded-full border border-border px-2.5 py-1 text-xs hover:border-accent hover:text-accent"
                    title={d.login}
                  >
                    {ROLE_LABELS[d.role]}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">Synthetic companies and users for the demo; Pro Labels is company #1.</p>
        </div>
      )}
    </div>
  )
}
