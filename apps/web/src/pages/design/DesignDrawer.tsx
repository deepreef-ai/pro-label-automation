import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, CheckCircle2, ExternalLink } from 'lucide-react'
import type { Design, Die, Job, Plate } from '@contract/types'
import {
  Badge,
  Button,
  DemoBadge,
  Input,
  ProgressSteps,
  QueryState,
  Sheet,
  SheetContent,
  Skeleton,
  StatusChip,
  toast,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatDate, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { DIE_LABEL, DIE_TONE, NEXT_STAGE, PLATE_LABEL, PLATE_TONE, PRESS_UNITS, STAGE_LABEL, STEPS, boardStage } from './shared'

export function DesignDrawer({
  jobCard,
  onOpenChange,
  plates,
  dies,
  onUpdated,
}: {
  jobCard: string | null
  onOpenChange: (v: boolean) => void
  plates: Plate[]
  dies: Die[]
  onUpdated: (d: Design) => void
}) {
  return (
    <Sheet open={!!jobCard} onOpenChange={onOpenChange}>
      {jobCard && (
        <SheetContent className="sm:max-w-xl" title={`Design · ${jobCard}`} description="Press set-up, colours, route, die and plates">
          <DrawerBody key={jobCard} jobCard={jobCard} plates={plates} dies={dies} onUpdated={onUpdated} />
        </SheetContent>
      )}
    </Sheet>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2.5 border-t border-border pt-5 first:border-t-0 first:pt-0">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </section>
  )
}

const FIELD =
  'h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

/** Design edits the colours per unit (+ anilox LPI), the route and the die; the server checks the rules
 * (press unit count, route starts with "Print <job's press>", usable die, plates only after approval). */
function SetupEditor({
  design,
  dies,
  press,
  onCancel,
  onSaved,
}: {
  design: Design
  dies: Die[]
  press: string
  onCancel: () => void
  onSaved: (d: Design) => void
}) {
  const unitAt = (n: number) => design.units.find((u) => u.unit === n)
  const [colours, setColours] = useState(() => Array.from({ length: PRESS_UNITS }, (_, i) => unitAt(i + 1)?.colour ?? ''))
  const [lpi, setLpi] = useState(() =>
    Array.from({ length: PRESS_UNITS }, (_, i) => (unitAt(i + 1)?.anilox_lpi ?? '').toString()),
  )
  const [route, setRoute] = useState(design.route.join(', '))
  const [dieId, setDieId] = useState(design.die_id ?? '')
  const [saving, setSaving] = useState(false)
  const usableDies = dies.filter((x) => x.status !== 'scrapped' && x.status !== 'damaged')

  const save = async () => {
    const units = colours
      .map((c, i) => ({
        unit: i + 1,
        colour: c.trim(),
        anilox_lpi: lpi[i].trim() ? Number(lpi[i]) : null,
        plate_id: unitAt(i + 1)?.plate_id ?? null,
      }))
      .filter((u) => u.colour)
    const patch: Partial<Design> = {
      units,
      route: route.split(',').map((x) => x.trim()).filter(Boolean),
      die_id: dieId || null,
    }
    setSaving(true)
    try {
      const saved = await api.put<Design>(`/api/design/${encodeURIComponent(design.job_card)}`, patch)
      onSaved({ ...design, ...patch, ...(saved?.job_card === design.job_card ? saved : {}) })
      toast.success(`${design.job_card}: set-up saved`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-border p-3">
      <p className="text-xs font-medium text-muted-foreground">Colour per unit (leave empty if unused) and anilox LPI</p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {colours.map((c, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-14 shrink-0 text-xs text-muted-foreground">Unit {i + 1}</span>
            <input
              className={FIELD}
              value={c}
              placeholder="Empty"
              aria-label={`Unit ${i + 1} colour`}
              onChange={(e) => setColours((xs) => xs.map((x, k) => (k === i ? e.target.value : x)))}
            />
            <input
              className={cn(FIELD, 'w-20')}
              value={lpi[i]}
              inputMode="numeric"
              placeholder="LPI"
              aria-label={`Unit ${i + 1} anilox LPI`}
              onChange={(e) => setLpi((xs) => xs.map((x, k) => (k === i ? e.target.value.replace(/[^0-9]/g, '') : x)))}
            />
          </div>
        ))}
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Route (comma separated; first step prints on the job's press)
        <input
          className={FIELD}
          value={route}
          placeholder={`Print ${press}, Inspection RW-1, Pack`}
          onChange={(e) => setRoute(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Die (Die Store)
        <select className={FIELD} value={dieId} onChange={(e) => setDieId(e.target.value)}>
          <option value="">No die yet</option>
          {usableDies.map((x) => (
            <option key={x.id} value={x.id}>
              {x.id} · {x.label_size} · {x.ups_across}×{x.ups_along} · {x.status}
            </option>
          ))}
        </select>
      </label>
      <div className="flex gap-2">
        <Button size="sm" onClick={save} loading={saving}>
          Save set-up
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function DrawerBody({
  jobCard,
  plates,
  dies,
  onUpdated,
}: {
  jobCard: string
  plates: Plate[]
  dies: Die[]
  onUpdated: (d: Design) => void
}) {
  const q = useApi<Design>(`/api/design/${encodeURIComponent(jobCard)}`)
  const jobQ = useApi<Job>(`/api/jobs/${encodeURIComponent(jobCard)}`)
  const [local, setLocal] = useState<Design | null>(null)
  const [saving, setSaving] = useState(false)
  const [approvedBy, setApprovedBy] = useState('')
  const [editing, setEditing] = useState(false)

  return (
    <QueryState
      query={q}
      loading={
        <div className="space-y-4">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      }
    >
      {(fetched) => {
        // Mock mode answers every job card with one fixture; keep the requested job card.
        const d = local ?? { ...fetched, job_card: jobCard }
        const job = jobQ.data && jobQ.data.job_card === jobCard ? jobQ.data : undefined
        const press = job?.machine_name ?? d.route.find((r) => /^print/i.test(r))?.replace(/^print\s*/i, '') ?? '—'
        const ups = d.ups_across * d.ups_along
        const die = d.die_id ? dies.find((x) => x.id === d.die_id) : undefined
        const dieMatch =
          die ??
          dies.find(
            (x) =>
              x.status !== 'scrapped' &&
              x.ups_across === d.ups_across &&
              x.ups_along === d.ups_along &&
              Math.abs(x.repeat_mm - d.repeat_mm) < 0.01 &&
              (!job || x.label_size === job.label_size),
          )
        const jobPlates = plates.filter((p) => d.plate_ids.includes(p.id) || p.job_card === jobCard)
        const next = NEXT_STAGE[d.stage]
        const units = Array.from({ length: PRESS_UNITS }, (_, i) => d.units.find((u) => u.unit === i + 1) ?? null)
        const online = d.route.filter((r) => /^print/i.test(r))
        const offline = d.route.filter((r) => !/^print/i.test(r))

        const advance = async () => {
          if (!next) return
          setSaving(true)
          try {
            const today = new Date().toISOString().slice(0, 10)
            const patch: Partial<Design> = { stage: next }
            if (next === 'proof_sent') patch.proof_sent_on = today
            if (next === 'approved') {
              patch.approved_on = today
              // the client's approval must say who approved the proof (SPEC: design rules)
              patch.approved_by = approvedBy.trim() || d.client_name
            }
            // the server fills plates (ordered / mounted) and the matching die on later stages
            const saved = await api.put<Design>(`/api/design/${encodeURIComponent(jobCard)}`, patch)
            const updated = { ...d, ...patch, ...(saved?.job_card === jobCard ? saved : {}) }
            setLocal(updated)
            onUpdated(updated)
            toast.success(`${jobCard}: ${STAGE_LABEL[next]}`)
          } catch (e) {
            toast.error((e as Error).message)
          } finally {
            setSaving(false)
          }
        }

        return (
          <div className="space-y-5">
            <Section title="Job">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-foreground">{d.client_name}</p>
                  <p className="text-sm text-muted-foreground">{d.product}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {d.designer} · artwork v{d.artwork_version}
                    {d.approved_on && ` · approved ${formatDate(d.approved_on)} by ${d.approved_by ?? 'client'}`}
                  </p>
                </div>
                <DemoBadge show={d.is_demo} />
              </div>
              <div className="overflow-x-auto pb-1">
                <ProgressSteps steps={STEPS} current={boardStage(d.stage)} complete={d.stage === 'done'} size="sm" className="min-w-[520px]" />
              </div>
              <div className="flex flex-wrap items-end gap-2">
                {next === 'approved' && (
                  <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-muted-foreground">
                    Approved by (client)
                    <Input
                      inputSize="sm"
                      value={approvedBy}
                      onChange={(e) => setApprovedBy(e.target.value)}
                      placeholder={d.client_name}
                      aria-label="Approved by (client)"
                    />
                  </label>
                )}
                {next && (
                  <Button size="sm" onClick={advance} loading={saving}>
                    Move to {STAGE_LABEL[next]} <ArrowRight />
                  </Button>
                )}
                <Button size="sm" variant="secondary" asChild>
                  <Link to={`/jobs/${jobCard}`}>
                    Job 360 <ExternalLink />
                  </Link>
                </Button>
              </div>
              {d.notes && <p className="rounded-md bg-surface-muted px-3 py-2 text-sm text-muted-foreground">{d.notes}</p>}
            </Section>

            <Section title="Press set-up">
              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-xs text-muted-foreground">Press</dt>
                  <dd className="font-medium text-foreground">{press}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Ups (across × along)</dt>
                  <dd className="tabular font-medium text-foreground">
                    {d.ups_across} × {d.ups_along} = {ups}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Repeat</dt>
                  <dd className="tabular font-medium text-foreground">{d.repeat_mm} mm</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Label size</dt>
                  <dd className="font-medium text-foreground">{job?.label_size ?? '—'}</dd>
                </div>
              </dl>
              <p className="text-xs text-muted-foreground">Press, ups and repeat come from the job card (Planning).</p>
              {d.stage !== 'done' && !editing && (
                <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                  Edit set-up (colours, route, die)
                </Button>
              )}
              {editing && (
                <SetupEditor
                  design={d}
                  dies={dies}
                  press={press}
                  onCancel={() => setEditing(false)}
                  onSaved={(updated) => {
                    setLocal(updated)
                    onUpdated(updated)
                    setEditing(false)
                  }}
                />
              )}
            </Section>

            <Section title={`Colour units (${d.units.length} of ${PRESS_UNITS})`}>
              <ul className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {units.map((u, i) => (
                  <li
                    key={i}
                    className={cn(
                      'rounded-md border px-2 py-1.5 text-xs',
                      u ? 'border-accent/25 bg-accent-soft text-accent-soft-foreground' : 'border-dashed border-border text-subtle-foreground',
                    )}
                  >
                    <span className="block text-2xs opacity-80">Unit {i + 1}</span>
                    <span className="block truncate font-medium" title={u?.colour}>
                      {u ? u.colour : 'Empty'}
                    </span>
                    {u && (
                      <span className="block truncate text-2xs opacity-80">
                        {u.anilox_lpi ? `${u.anilox_lpi} LPI` : '—'}
                        {u.plate_id ? ` · ${u.plate_id}` : ''}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Route">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-xs text-muted-foreground">Online (on press)</p>
                  <ul className="space-y-1">
                    {online.length ? (
                      online.map((r) => (
                        <li key={r}>
                          <Badge tone="accent">{r}</Badge>
                        </li>
                      ))
                    ) : (
                      <li className="text-sm text-muted-foreground">—</li>
                    )}
                  </ul>
                </div>
                <div>
                  <p className="mb-1.5 text-xs text-muted-foreground">Offline (after press)</p>
                  <ul className="space-y-1">
                    {offline.length ? (
                      offline.map((r) => (
                        <li key={r}>
                          <Badge tone="neutral">{r}</Badge>
                        </li>
                      ))
                    ) : (
                      <li className="text-sm text-muted-foreground">—</li>
                    )}
                  </ul>
                </div>
              </div>
              <p className="rounded-md border border-border bg-surface-muted px-3 py-2 text-sm text-foreground">
                <span className="text-xs text-muted-foreground">Auto route: </span>
                {d.route.length ? d.route.join(' → ') : 'Not set yet'}
              </p>
            </Section>

            <Section title="Die check (Die Store)">
              {dieMatch ? (
                <div
                  className={cn(
                    'flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-sm',
                    dieMatch.status === 'ok' ? 'border-ok/20 bg-ok-soft' : 'border-warn/25 bg-warn-soft',
                  )}
                >
                  {dieMatch.status === 'ok' ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
                  ) : (
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                  )}
                  <div className="min-w-0 text-foreground">
                    <p className="font-medium">
                      {d.die_id ? `Die ${dieMatch.id} assigned` : `Matching die ${dieMatch.id} in store`} ·{' '}
                      <StatusChip tone={DIE_TONE[dieMatch.status]} size="sm">
                        {DIE_LABEL[dieMatch.status]}
                      </StatusChip>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {dieMatch.type} · {dieMatch.label_size} · {dieMatch.ups_across} × {dieMatch.ups_along} · repeat {dieMatch.repeat_mm} mm ·{' '}
                      {formatNumber(dieMatch.impressions)} impressions · {dieMatch.location}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-2.5 rounded-md border border-danger/20 bg-danger-soft px-3 py-2.5 text-sm text-danger-foreground">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  No die in store for {d.ups_across} × {d.ups_along} ups at {d.repeat_mm} mm repeat. Order a new die.
                </div>
              )}
            </Section>

            <Section title={`Plates (${jobPlates.length})`}>
              {jobPlates.length ? (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {jobPlates.map((p) => (
                    <li key={p.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                      <span className="min-w-0">
                        <span className="font-mono text-xs font-medium text-foreground">{p.id}</span>
                        <span className="text-muted-foreground">
                          {' '}
                          · unit {p.unit} {p.colour} · rack {p.rack}
                        </span>
                      </span>
                      <StatusChip tone={PLATE_TONE[p.status]} size="sm">
                        {PLATE_LABEL[p.status]}
                      </StatusChip>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {d.stage === 'plates_ordered' ? 'Plates ordered, not received yet.' : 'No plates made for this job yet.'}
                </p>
              )}
            </Section>
          </div>
        )
      }}
    </QueryState>
  )
}
