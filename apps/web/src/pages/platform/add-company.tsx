import { useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, CheckCircle2, Download, FileSpreadsheet, Upload } from 'lucide-react'
import type { CompanyCreate, CompanyCreated, ImportFix, ImportResult, ImportSheet } from '@contract/types'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  DataTable,
  Field,
  Input,
  PageHeader,
  ProgressSteps,
  StatusChip,
  toast,
  type Column,
} from '@/components/ui'
import { api } from '@/lib/api'
import { formatINRWhole } from '@/lib/format'
import { APP_DOMAIN } from '@/lib/session'
import { PlatformOnly, downloadCsv } from './shared'

/** Screen 18 · Platform: Add a company (W2 #57). Six steps; no new server or code per company. */
export default function AddCompanyPage() {
  return (
    <PlatformOnly>
      <Wizard />
    </PlatformOnly>
  )
}

const STEPS = [
  { key: 'details', label: 'Company details' },
  { key: 'rules', label: 'Rules & limits' },
  { key: 'users', label: 'Users & roles' },
  { key: 'import', label: 'Import data' },
  { key: 'connect', label: 'Connect ERP / Tally' },
  { key: 'live', label: 'Parallel run → live' },
] as const
type StepKey = (typeof STEPS)[number]['key']

const SLUG_RE = /^[a-z0-9-]{3,30}$/
const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
    .slice(0, 30)

const SHEET_LABEL: Record<ImportSheet['sheet'], string> = {
  clients: 'Clients',
  vendors: 'Vendors',
  items: 'Items (paper, film, ink)',
  machines: 'Machines',
  opening_stock: 'Opening stock',
  unpaid_invoices: 'Unpaid invoices',
}

function Wizard() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [step, setStep] = useState<StepKey>((params.get('step') as StepKey) || 'details')
  const [created, setCreated] = useState<CompanyCreated | null>(null)
  const companyId = created?.company.id ?? params.get('company')
  const idx = STEPS.findIndex((s) => s.key === step)
  const go = (k: StepKey) => setStep(k)
  const next = () => setStep(STEPS[Math.min(idx + 1, STEPS.length - 1)].key)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Add a company"
        subtitle="Six steps. No new server or code: the company gets its own isolated space on the shared platform."
        meta={created ? <Badge tone="info">Setting up: {created.company.name}</Badge> : undefined}
      />
      <Card>
        <CardContent className="py-4">
          <ProgressSteps steps={STEPS.map((s) => ({ key: s.key, label: s.label }))} current={step} />
        </CardContent>
      </Card>

      {step === 'details' && <DetailsStep onCreated={(c) => (setCreated(c), next())} />}
      {step === 'rules' && <RulesStep onBack={() => go('details')} onNext={next} />}
      {step === 'users' && <UsersStep created={created} onBack={() => go('rules')} onNext={next} />}
      {step === 'import' && <ImportStep companyId={companyId} onBack={() => go('users')} onNext={next} />}
      {step === 'connect' && <ConnectStep onBack={() => go('import')} onNext={next} />}
      {step === 'live' && (
        <LiveStep
          name={created?.company.name ?? 'The company'}
          onBack={() => go('connect')}
          onFinish={() => {
            toast.success('Company set up. It starts in parallel run beside Excel.')
            navigate('/platform')
          }}
        />
      )}
    </div>
  )
}

function StepNav({
  onBack,
  onNext,
  nextLabel = 'Next',
  nextDisabled,
}: {
  onBack?: () => void
  onNext: () => void
  nextLabel?: string
  nextDisabled?: boolean
}) {
  return (
    <div className="flex items-center justify-between pt-2">
      {onBack ? (
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft /> Back
        </Button>
      ) : (
        <span />
      )}
      <Button onClick={onNext} disabled={nextDisabled}>
        {nextLabel} <ArrowRight />
      </Button>
    </div>
  )
}

/* ---------------- Step 1 ---------------- */

function DetailsStep({ onCreated }: { onCreated: (c: CompanyCreated) => void }) {
  const [f, setF] = useState<CompanyCreate>({
    name: '',
    slug: '',
    city: '',
    state: '',
    gstin: '',
    admin_name: '',
    admin_login: '',
    ai_budget_month: 1000,
  })
  const [slugTouched, setSlugTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<Record<string, string>>({})
  const set = (k: keyof CompanyCreate, v: string | number) =>
    setF((p) => ({ ...p, [k]: v, ...(k === 'name' && !slugTouched ? { slug: slugify(String(v)) } : {}) }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    const errors: Record<string, string> = {}
    if (!f.name.trim()) errors.name = 'Enter the company name.'
    if (!SLUG_RE.test(f.slug)) errors.slug = '3–30 small letters, numbers or "-".'
    if (f.gstin && f.gstin.trim().length !== 15) errors.gstin = 'GSTIN must be 15 characters.'
    if (!f.admin_name.trim()) errors.admin_name = "Enter the company admin's name."
    if (!f.admin_login.trim()) errors.admin_login = 'Mobile number or e-mail.'
    setErr(errors)
    if (Object.keys(errors).length) return
    setBusy(true)
    try {
      const body: CompanyCreate = { ...f, gstin: f.gstin?.trim() || null }
      const res = await api.post<CompanyCreated>('/api/platform/companies', body)
      // Mock mode answers with the contract sample; show what the user typed instead.
      const company = res?.company
        ? { ...res.company, name: f.name.trim(), slug: f.slug, city: f.city || null, state: f.state || null }
        : null
      if (!company) throw new Error('Unexpected answer from the server.')
      onCreated({ company, admin: { ...res.admin, name: f.admin_name, login: f.admin_login } })
      toast.success(`${f.name.trim()} created with its own isolated space`)
    } catch (ex) {
      toast.error((ex as Error).message || 'Could not create the company')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Step 1 · Company details"
        description="The company and its first admin (role Owner). The admin then invites their own users."
      />
      <CardContent>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-2" noValidate>
          <Field label="Company name" htmlFor="name" error={err.name}>
            <Input id="name" value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Ganga Pack Labels" />
          </Field>
          <Field label="Web address" htmlFor="slug" error={err.slug} hint={`${f.slug || 'company'}.${APP_DOMAIN}`}>
            <Input
              id="slug"
              value={f.slug}
              onChange={(e) => {
                setSlugTouched(true)
                set('slug', e.target.value.toLowerCase())
              }}
            />
          </Field>
          <Field label="City" htmlFor="city">
            <Input id="city" value={f.city ?? ''} onChange={(e) => set('city', e.target.value)} />
          </Field>
          <Field label="State" htmlFor="state">
            <Input id="state" value={f.state ?? ''} onChange={(e) => set('state', e.target.value)} />
          </Field>
          <Field label="GSTIN (optional)" htmlFor="gstin" error={err.gstin}>
            <Input id="gstin" value={f.gstin ?? ''} onChange={(e) => set('gstin', e.target.value.toUpperCase())} maxLength={15} />
          </Field>
          <Field label="AI budget / month (₹)" htmlFor="ai" hint="Alarm at 80%; at 100% AI features use their non-AI fallback.">
            <Input
              id="ai"
              type="number"
              min={0}
              step={100}
              value={f.ai_budget_month ?? 1000}
              onChange={(e) => set('ai_budget_month', Number(e.target.value))}
            />
          </Field>
          <Field label="Company admin name" htmlFor="admin_name" error={err.admin_name}>
            <Input id="admin_name" value={f.admin_name} onChange={(e) => set('admin_name', e.target.value)} />
          </Field>
          <Field label="Admin mobile or e-mail" htmlFor="admin_login" error={err.admin_login}>
            <Input id="admin_login" value={f.admin_login} onChange={(e) => set('admin_login', e.target.value)} />
          </Field>
          <div className="flex justify-end md:col-span-2">
            <Button type="submit" loading={busy}>
              Create company <ArrowRight />
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

/* ---------------- Step 2 ---------------- */

function RulesStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const [r, setR] = useState({ wastage: 15, overprint: 10, gst: 18, grace: 15, credit: 30 })
  const rows: [keyof typeof r, string, string][] = [
    ['wastage', 'Wastage limit', '%'],
    ['overprint', 'Over-production limit', '%'],
    ['gst', 'GST', '%'],
    ['grace', 'Lock grace after due date', 'days'],
    ['credit', 'Default client credit', 'days'],
  ]
  return (
    <Card>
      <CardHeader
        title="Step 2 · Rules & limits"
        description="Starts from the standard defaults; the company owner can change them any time in Settings (their company only)."
      />
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {rows.map(([k, label, unit]) => (
            <Field key={k} label={label} htmlFor={k} hint={unit}>
              <Input
                id={k}
                type="number"
                min={0}
                value={r[k]}
                onChange={(e) => setR((p) => ({ ...p, [k]: Number(e.target.value) }))}
              />
            </Field>
          ))}
        </div>
        <StepNav onBack={onBack} onNext={onNext} />
      </CardContent>
    </Card>
  )
}

/* ---------------- Step 3 ---------------- */

function UsersStep({ created, onBack, onNext }: { created: CompanyCreated | null; onBack: () => void; onNext: () => void }) {
  return (
    <Card>
      <CardHeader
        title="Step 3 · Users & roles"
        description="The first admin is invited now; they add their own team (store, press, QC, accounts…) in Users & connections."
      />
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between rounded-md border border-border p-3">
          <div>
            <div className="font-medium">{created?.admin.name ?? 'Company admin'}</div>
            <div className="text-sm text-muted-foreground">{created?.admin.login ?? '—'} · Owner (company admin)</div>
          </div>
          <StatusChip tone="info">Invited · OTP on first sign-in</StatusChip>
        </div>
        <p className="text-sm text-muted-foreground">
          Each user belongs to this company only. Platform staff cannot see the company&apos;s jobs, stock or money.
        </p>
        <StepNav onBack={onBack} onNext={onNext} />
      </CardContent>
    </Card>
  )
}

/* ---------------- Step 4 ---------------- */

function ImportStep({ companyId, onBack, onNext }: { companyId: string | null; onBack: () => void; onNext: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)

  async function upload(file: File) {
    if (!companyId) {
      toast.error('Create the company first (step 1).')
      return
    }
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post<ImportResult>(`/api/platform/companies/${companyId}/import`, fd)
      setResult({ ...res, file_name: file.name })
    } catch (ex) {
      toast.error((ex as Error).message || 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  const sheetCols: Column<ImportSheet>[] = [
    { key: 'sheet', header: 'Sheet', cell: (s) => SHEET_LABEL[s.sheet] ?? s.sheet },
    { key: 'rows', header: 'Rows', align: 'right', cell: (s) => s.rows },
    { key: 'good', header: 'Saved', align: 'right', cell: (s) => s.good },
    {
      key: 'held',
      header: 'Need fixing',
      align: 'right',
      cell: (s) => (s.held_back ? <b className="text-warn-foreground">{s.held_back}</b> : 0),
    },
    {
      key: 'status',
      header: 'Check',
      cell: (s) => (
        <StatusChip tone={s.status === 'ok' ? 'ok' : s.status === 'warn' ? 'warn' : 'danger'}>
          {s.status === 'ok' ? 'OK' : (s.checks.find((c) => c.status !== 'ok')?.message ?? s.status)}
        </StatusChip>
      ),
    },
  ]
  const fixCols: Column<ImportFix>[] = [
    {
      key: 'where',
      header: 'Where',
      cell: (f) => `${SHEET_LABEL[f.sheet as ImportSheet['sheet']] ?? f.sheet} · row ${f.row} · ${f.column}`,
    },
    { key: 'value', header: 'Value', cell: (f) => <code className="text-xs">{f.value ?? '(empty)'}</code> },
    { key: 'problem', header: 'Problem', cell: (f) => f.problem },
    { key: 'fix', header: 'How to fix', cell: (f) => f.fix },
  ]

  return (
    <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
      <Card>
        <CardHeader
          title="Step 4 · Import opening data"
          description="Upload the standard template. Every row is checked; good rows are saved with this company's ID, bad rows are held back."
        />
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 rounded-lg border-2 border-dashed border-accent/40 bg-accent-soft/40 p-4">
            <FileSpreadsheet className="size-7 text-accent" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="font-medium">{result ? result.file_name : 'Choose the filled template (.xlsx)'}</div>
              <div className="text-sm text-muted-foreground">
                Sheets: clients, vendors, items, machines, opening stock, unpaid invoices
              </div>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void upload(f)
                e.target.value = ''
              }}
            />
            <Button variant="secondary" onClick={() => fileRef.current?.click()} loading={busy}>
              <Upload /> {result ? 'Re-upload' : 'Upload'}
            </Button>
          </div>

          {result && (
            <>
              <DataTable columns={sheetCols} rows={result.sheets} rowKey={(s) => s.sheet} dense />
              {result.fixes.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">Fix list ({result.fixes.length} rows)</h3>
                    <Button
                      size="sm"
                      onClick={() =>
                        downloadCsv(`fix-list-${result.import_id}.csv`, result.fixes as unknown as Record<string, unknown>[])
                      }
                    >
                      <Download /> Download fix list
                    </Button>
                  </div>
                  <DataTable
                    columns={fixCols}
                    rows={result.fixes}
                    rowKey={(f, i) => `${f.sheet}-${f.row}-${f.column}-${i}`}
                    dense
                    maxHeight={260}
                  />
                </div>
              )}
            </>
          )}
          <StepNav onBack={onBack} onNext={onNext} nextLabel="Next: connect ERP" nextDisabled={!result} />
        </CardContent>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title="Result" />
          <CardContent className="space-y-2 text-sm">
            {result ? (
              <>
                <Row k="Rows checked" v={result.totals.rows} />
                <Row k="Saved for this company" v={result.totals.good} />
                <Row k="Held back (fix list)" v={result.totals.held_back} />
                <Row
                  k="Status"
                  v={result.status === 'ok' ? 'All saved' : result.status === 'partial' ? 'Partly saved' : 'Failed'}
                />
              </>
            ) : (
              <p className="text-muted-foreground">Upload the template to see the checks.</p>
            )}
          </CardContent>
        </Card>
        <p className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2.5 text-sm text-warn-foreground">
          <b>Bad rows never load silently.</b> They stay out until fixed and re-uploaded. Nothing is ever copied from another
          company.
        </p>
        <p className="rounded-md border border-accent/30 bg-accent-soft px-3 py-2.5 text-sm text-accent-soft-foreground">
          <b>Target:</b> 1–2 weeks per company, mostly data clean-up, then 2–4 weeks beside Excel before switching.
        </p>
      </div>
    </div>
  )
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="flex justify-between border-b border-border pb-1.5 last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className="font-medium tabular">{v}</span>
    </div>
  )
}

/* ---------------- Step 5 ---------------- */

function ConnectStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const [erp, setErp] = useState<'api' | 'csv' | 'none'>('csv')
  const [tally, setTally] = useState(true)
  const opts = useMemo(
    () => [
      { v: 'api' as const, t: 'ERP API', d: 'Pull GRNs and issues every 15 minutes' },
      { v: 'csv' as const, t: 'CSV export', d: 'ERP drops a file in a watched folder every 15 minutes' },
      { v: 'none' as const, t: 'No ERP yet', d: 'Store enters GRNs and issues in the app' },
    ],
    [],
  )
  return (
    <Card>
      <CardHeader title="Step 5 · Connect ERP / Tally" description="This company's own links; other companies have their own." />
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          {opts.map((o) => (
            <button
              key={o.v}
              type="button"
              onClick={() => setErp(o.v)}
              aria-pressed={erp === o.v}
              className={`rounded-lg border p-3 text-left transition-colors ${erp === o.v ? 'border-accent bg-accent-soft' : 'border-border hover:border-border-strong'}`}
            >
              <div className="font-medium">{o.t}</div>
              <div className="text-sm text-muted-foreground">{o.d}</div>
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={tally}
            onChange={(e) => setTally(e.target.checked)}
            className="size-4 accent-[var(--accent)]"
          />
          Tally: push approved invoices, read ledgers monthly
        </label>
        <StepNav onBack={onBack} onNext={onNext} />
      </CardContent>
    </Card>
  )
}

/* ---------------- Step 6 ---------------- */

function LiveStep({ name, onBack, onFinish }: { name: string; onBack: () => void; onFinish: () => void }) {
  return (
    <Card>
      <CardHeader
        title="Step 6 · Parallel run → live"
        description={`${name} runs beside Excel for 2–4 weeks; when the numbers match, it switches to live.`}
      />
      <CardContent className="space-y-3 text-sm">
        {[
          'Status set to Parallel run; the owner gets the 9 am digest from day 1',
          'Agents run every morning for this company only',
          `AI budget alarm at 80% (from step 1); shared platform cost ≈ ${formatINRWhole(1500)}–${formatINRWhole(2600)} per company / month`,
          'Switch to Live when system totals match Excel / Tally within 1%',
        ].map((t) => (
          <div key={t} className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
            {t}
          </div>
        ))}
        <StepNav onBack={onBack} onNext={onFinish} nextLabel="Finish setup" />
      </CardContent>
    </Card>
  )
}
