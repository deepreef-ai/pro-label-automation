import { useMemo, useState, type FormEvent } from 'react'
import { currentCompany } from '@/lib/session'
import { Link, useNavigate } from 'react-router-dom'
import { Cloud, Cpu, Info, Lock, RotateCcw, Save } from 'lucide-react'
import type { Settings, SettingsUpdate } from '@contract/types'
import {
  Badge,
  Button,
  Card,
  CardFooter,
  CardHeader,
  Field,
  Input,
  PageHeader,
  PageSkeleton,
  QueryState,
  Switch,
  toast,
} from '@/components/ui'
import { API_MODE, api, useApi } from '@/lib/api'
import { formatDateTime, formatPercent } from '@/lib/format'
import { ROLE_LABELS, useRole } from '@/lib/role'
import { cn } from '@/lib/utils'
import { SETTINGS_DEFAULTS, setMockSettings, useMockSettings } from './store'

type PctKey =
  | 'wastage_tol'
  | 'overprod_tol'
  | 'material_tol'
  | 'ink_tol'
  | 'slit_tol'
  | 'grn_rate_tol'
  | 'gst_rate'
  | 'planning_extra'
  | 'admin_pct'
type DayKey = 'grace_days' | 'msme_days'
type NumKey = PctKey | DayKey

interface FieldDef {
  key: NumKey
  label: string
  hint: string
  unit: '%' | 'days'
  min: number
  max: number
}

const TOLERANCES: FieldDef[] = [
  { key: 'wastage_tol', label: 'Wastage', hint: 'Flag a run when wastage is above this share of required metres.', unit: '%', min: 0, max: 100 },
  { key: 'overprod_tol', label: 'Over-production', hint: 'Flag when printed is above order qty by more than this.', unit: '%', min: 0, max: 100 },
  { key: 'material_tol', label: 'Material issue', hint: 'Flag when issued differs from planned metres by more than this.', unit: '%', min: 0, max: 100 },
  { key: 'ink_tol', label: 'Ink', hint: 'Flag when actual ink differs from the estimate by more than this.', unit: '%', min: 0, max: 100 },
  { key: 'slit_tol', label: 'Slitting trim', hint: 'Flag when slitting trim is above this.', unit: '%', min: 0, max: 100 },
  { key: 'grn_rate_tol', label: 'GRN rate', hint: 'Flag when a GRN rate differs from the item master by more than this.', unit: '%', min: 0, max: 100 },
]

const CREDIT: FieldDef[] = [
  { key: 'grace_days', label: 'Lock grace', hint: 'A client locks when an invoice is unpaid this many days after due.', unit: 'days', min: 0, max: 180 },
  { key: 'msme_days', label: 'MSME payment limit', hint: 'MSME supplier bills fall due within this many days (law: 45).', unit: 'days', min: 1, max: 45 },
]

const COSTING: FieldDef[] = [
  { key: 'gst_rate', label: 'GST', hint: 'Applied to invoice taxable value.', unit: '%', min: 0, max: 28 },
  { key: 'planning_extra', label: 'Planning extra', hint: 'Added to required metres when planning material.', unit: '%', min: 0, max: 50 },
  { key: 'admin_pct', label: 'Admin share', hint: 'Admin cost share charged to each job for job profit.', unit: '%', min: 0, max: 50 },
]

const ALL_FIELDS = [...TOLERANCES, ...CREDIT, ...COSTING]

type FormValues = Record<NumKey, string>

function toForm(s: Settings): FormValues {
  const out = {} as FormValues
  for (const f of ALL_FIELDS) {
    const v = s[f.key]
    out[f.key] = f.unit === '%' ? String(Number((v * 100).toFixed(2))) : String(v)
  }
  return out
}

function validate(values: FormValues): Partial<Record<NumKey, string>> {
  const errors: Partial<Record<NumKey, string>> = {}
  for (const f of ALL_FIELDS) {
    const raw = values[f.key].trim()
    const n = Number(raw)
    if (raw === '' || !Number.isFinite(n)) errors[f.key] = 'Enter a number'
    else if (f.unit === 'days' && !Number.isInteger(n)) errors[f.key] = 'Whole days only'
    else if (n < f.min || n > f.max) errors[f.key] = `Between ${f.min} and ${f.max}${f.unit === '%' ? '%' : ' days'}`
  }
  return errors
}

function parsed(f: FieldDef, raw: string): number {
  const n = Number(raw)
  return f.unit === '%' ? Number((n / 100).toFixed(4)) : n
}

export default function SettingsPage() {
  const q = useApi<Settings>('/api/settings')
  // Mock mode: edits saved this session win over the (static) fixture. See ./store.ts.
  const mock = useMockSettings()
  const effective = API_MODE === 'mock' && mock ? mock : q.data
  const role = useRole()
  const isOwner = role === 'owner'

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        subtitle={`Tolerances, credit rules and AI mode used by every screen, alert and agent. These apply to ${currentCompany().name} only.`}
        meta={!isOwner ? <Badge tone="neutral">Read only</Badge> : undefined}
      />
      <QueryState query={{ ...q, data: effective }} loading={<PageSkeleton />}>
        {(s) => (
          <SettingsForm
            key={role}
            settings={s}
            isOwner={isOwner}
            roleLabel={ROLE_LABELS[role]}
            onSaved={q.refetch}
          />
        )}
      </QueryState>
    </div>
  )
}

function SettingsForm({
  settings,
  isOwner,
  roleLabel,
  onSaved,
}: {
  settings: Settings
  isOwner: boolean
  roleLabel: string
  onSaved: () => void
}) {
  const navigate = useNavigate()
  const initial = useMemo(() => toForm(settings), [settings])
  const [values, setValues] = useState<FormValues>(initial)
  const [aiMode, setAiMode] = useState<Settings['ai_mode']>(settings.ai_mode)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)

  const errors = validate(values)
  const hasErrors = Object.keys(errors).length > 0
  const changed = ALL_FIELDS.filter((f) => parsed(f, values[f.key]) !== settings[f.key])
  const aiChanged = aiMode !== settings.ai_mode
  const dirty = changed.length > 0 || aiChanged
  const readOnly = !isOwner

  const set = (key: NumKey, v: string) => {
    setTouched(true)
    setValues((cur) => ({ ...cur, [key]: v }))
  }

  const reset = () => {
    setValues(initial)
    setAiMode(settings.ai_mode)
    setTouched(false)
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (readOnly || hasErrors || !dirty) return
    const body: SettingsUpdate = {}
    for (const f of changed) body[f.key] = parsed(f, values[f.key])
    if (aiChanged) body.ai_mode = aiMode
    setSaving(true)
    try {
      const res = await api.put<Settings>('/api/settings', body)
      if (API_MODE === 'mock') {
        // The mock PUT echoes a fixed fixture, so keep the real edit in the in-memory store.
        setMockSettings({ ...settings, ...body, updated_at: new Date().toISOString(), updated_by: 'owner' })
      } else if (res) {
        onSaved()
      }
      setSavedAt(new Date().toISOString())
      toast.success('Settings saved', {
        description: 'Alerts recalculate on the Dashboard.',
        action: { label: 'Open Dashboard', onClick: () => navigate('/') },
      })
    } catch (err) {
      toast.error('Could not save settings', { description: (err as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const renderField = (f: FieldDef) => {
    const id = `set-${f.key}`
    const def = SETTINGS_DEFAULTS[f.key]
    const isChanged = changed.includes(f)
    return (
      <Field
        key={f.key}
        label={
          <span className="flex items-center gap-2">
            {f.label}
            {isChanged && !readOnly && (
              <Badge size="sm" tone="accent">
                Edited
              </Badge>
            )}
          </span>
        }
        htmlFor={id}
        hint={`${f.hint} Default ${f.unit === '%' ? formatPercent(def, { digits: 0 }) : `${def} days`}.`}
        error={touched ? errors[f.key] : undefined}
      >
        <div className="relative">
          <Input
            id={id}
            inputMode="decimal"
            value={values[f.key]}
            onChange={(e) => set(f.key, e.target.value)}
            disabled={readOnly}
            readOnly={readOnly}
            aria-invalid={touched && !!errors[f.key]}
            className={cn('tabular pr-14', touched && errors[f.key] && 'border-danger')}
          />
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">
            {f.unit}
          </span>
        </div>
      </Field>
    )
  }

  return (
    <form onSubmit={save} className="space-y-6" noValidate>
      {readOnly && (
        <div className="flex items-start gap-3 rounded-lg border border-border bg-surface-muted px-4 py-3 text-sm text-muted-foreground">
          <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            Only the owner can change settings. You are signed in as <strong className="text-foreground">{roleLabel}</strong>,
            so these values are read only.
          </p>
        </div>
      )}

      {savedAt && (
        <div
          role="status"
          className="flex flex-col gap-2 rounded-lg border border-ok/20 bg-ok-soft px-4 py-3 text-sm text-ok-foreground sm:flex-row sm:items-center sm:justify-between"
        >
          <span>Saved {formatDateTime(savedAt)}. Alerts recalculate on the Dashboard.</span>
          <Link to="/" className="font-medium underline underline-offset-2">
            Open Dashboard
          </Link>
        </div>
      )}

      <Card>
        <CardHeader title="Tolerances" description="How far actuals may drift before the system raises a flag." />
        <div className="grid gap-5 p-5 sm:grid-cols-2 xl:grid-cols-3">{TOLERANCES.map(renderField)}</div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Credit and payables" description="Client lock and supplier due-date rules." />
          <div className="grid gap-5 p-5 sm:grid-cols-2">{CREDIT.map(renderField)}</div>
        </Card>
        <Card>
          <CardHeader title="Tax and costing" description="Used for invoices, planning and job profit." />
          <div className="grid gap-5 p-5 sm:grid-cols-2">{COSTING.map(renderField)}</div>
        </Card>
      </div>

      <Card>
        <CardHeader title="AI mode" description="Where the chatbot and agents run their language model." />
        <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 text-base font-medium',
                aiMode !== 'cloud' ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              <Cpu className="size-4" aria-hidden />
              Local
            </span>
            <Switch
              aria-label="Use cloud AI"
              checked={aiMode === 'cloud'}
              onCheckedChange={(c) => {
                setTouched(true)
                setAiMode(c ? 'cloud' : 'local')
              }}
              disabled={readOnly}
            />
            <span
              className={cn(
                'inline-flex items-center gap-1.5 text-base font-medium',
                aiMode === 'cloud' ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              <Cloud className="size-4" aria-hidden />
              Cloud
            </span>
            {aiChanged && !readOnly && (
              <Badge size="sm" tone="accent">
                Edited
              </Badge>
            )}
          </div>
          <p className="flex max-w-lg items-start gap-2 text-sm text-muted-foreground">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            {aiMode === 'cloud'
              ? 'Cloud: better answers. Client and vendor names are anonymised before any call leaves the plant.'
              : aiMode === 'local'
                ? 'Local: nothing leaves the plant. Answers may be shorter.'
                : 'AI is off: agents and chat use fixed templates.'}
          </p>
        </div>
      </Card>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">
          Last changed {formatDateTime(settings.updated_at)}
          {settings.updated_by ? ` by ${settings.updated_by}` : ''}
          {API_MODE === 'mock' && ' · demo mode: saved for this session only'}
        </p>
        {!readOnly && (
          <CardFooter className="border-0 p-0">
            <Button type="button" variant="ghost" onClick={reset} disabled={!dirty || saving}>
              <RotateCcw aria-hidden />
              Reset
            </Button>
            <Button type="submit" loading={saving} disabled={!dirty || hasErrors || saving}>
              <Save aria-hidden />
              Save changes
            </Button>
          </CardFooter>
        )}
      </div>
    </form>
  )
}
