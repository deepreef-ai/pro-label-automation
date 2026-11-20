import { useState } from 'react'
import type { Finding } from '@contract/types'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  Segmented,
  Textarea,
  toast,
} from '@/components/ui'
import { agentsStore, messagesOf } from './store'

type Lang = 'en' | 'hi'

interface MsgDraft {
  channel?: string
  to?: string
  subject?: string
  en: string
  hi: string | null
  lang: Lang
}

const REMINDER =
  /^Dear (.+?), Rs ([\d,.]+) is overdue\. Your account will be put on hold on (\d{4}-\d{2}-\d{2})\. Kindly arrange payment\. - (.+)$/

/** Deterministic Hindi version of the standard reminder (no LLM needed). */
function toHindi(en: string): string | null {
  const m = REMINDER.exec(en.trim())
  if (!m) return null
  const [, name, amount, date, from] = m
  const [y, mo, d] = date.split('-')
  return `प्रिय ${name} जी, ₹${amount} की राशि बकाया है। ${d}-${mo}-${y} को आपका खाता होल्ड पर कर दिया जाएगा। कृपया भुगतान की व्यवस्था करें। - ${from === 'Accounts' ? 'अकाउंट्स' : from}`
}

function initMessages(f: Finding): MsgDraft[] {
  return messagesOf(f).map((m) => {
    const body = m.body ?? ''
    const isHi = /[ऀ-ॿ]/.test(body)
    return { channel: m.channel, to: m.to, subject: m.subject, en: isHi ? '' : body, hi: isHi ? body : toHindi(body), lang: isHi ? 'hi' : 'en' }
  })
}

type Primitive = string | number | boolean | null

export function EditFindingDialog({ finding, onClose }: { finding: Finding | null; onClose: () => void }) {
  return (
    <Dialog open={!!finding} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="lg">{finding && <EditBody key={finding.id} finding={finding} onClose={onClose} />}</DialogContent>
    </Dialog>
  )
}

function EditBody({ finding, onClose }: { finding: Finding; onClose: () => void }) {
  const isMessages = finding.suggested_action.type === 'draft_messages'
  const payload = finding.suggested_action.payload
  const [msgs, setMsgs] = useState<MsgDraft[]>(() => initMessages(finding))
  const primitiveKeys = Object.keys(payload).filter((k) => {
    const v = payload[k]
    return v === null || ['string', 'number', 'boolean'].includes(typeof v)
  })
  const complexKeys = Object.keys(payload).filter((k) => !primitiveKeys.includes(k) && !(isMessages && k === 'messages'))
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(primitiveKeys.map((k) => [k, payload[k] == null ? '' : String(payload[k])])),
  )
  const [json, setJson] = useState<Record<string, string>>(() =>
    Object.fromEntries(complexKeys.map((k) => [k, JSON.stringify(payload[k], null, 2)])),
  )
  const [busy, setBusy] = useState(false)

  const jsonErrors = Object.fromEntries(
    Object.entries(json).map(([k, v]) => {
      try {
        JSON.parse(v)
        return [k, null]
      } catch {
        return [k, 'Not valid JSON']
      }
    }),
  )
  const hasErrors = Object.values(jsonErrors).some(Boolean)

  const updateMsg = (i: number, patch: Partial<MsgDraft>) => setMsgs((list) => list.map((m, j) => (j === i ? { ...m, ...patch } : m)))

  const save = async () => {
    const next: Record<string, unknown> = { ...payload }
    for (const k of primitiveKeys) {
      const orig = payload[k] as Primitive
      const raw = fields[k]
      next[k] =
        typeof orig === 'number' ? (raw === '' || Number.isNaN(Number(raw)) ? orig : Number(raw)) : typeof orig === 'boolean' ? raw === 'true' : raw
    }
    for (const k of complexKeys) next[k] = JSON.parse(json[k])
    if (isMessages) {
      next.messages = msgs.map((m) => ({
        channel: m.channel,
        to: m.to,
        ...(m.subject ? { subject: m.subject } : {}),
        body: m.lang === 'hi' ? (m.hi ?? m.en) : m.en,
        lang: m.lang,
      }))
    }
    setBusy(true)
    try {
      await agentsStore.edit(finding, next)
      toast.success('Draft updated', { description: 'Approve the card to send it.' })
      onClose()
    } catch (e) {
      toast.error('Could not save the edit', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Edit suggested action</DialogTitle>
        <DialogDescription>{finding.title}</DialogDescription>
      </DialogHeader>

      {isMessages && (
        <div className="space-y-4">
          {msgs.map((m, i) => (
            <div key={i} className="space-y-2 rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Badge tone={m.channel === 'email' ? 'info' : 'ok'} size="sm">
                    {m.channel === 'email' ? 'Email' : 'WhatsApp'}
                  </Badge>
                  <span className="truncate text-sm font-medium text-foreground">{m.to}</span>
                </div>
                <Segmented<Lang>
                  aria-label={`Language for message to ${m.to ?? ''}`}
                  value={m.lang}
                  onChange={(lang) => {
                    if (lang === 'hi' && m.hi === null) updateMsg(i, { lang, hi: m.en })
                    else updateMsg(i, { lang })
                  }}
                  options={[
                    { value: 'en', label: 'EN' },
                    { value: 'hi', label: 'हिंदी' },
                  ]}
                />
              </div>
              {m.subject !== undefined && (
                <Input aria-label="Subject" value={m.subject} onChange={(e) => updateMsg(i, { subject: e.target.value })} inputSize="sm" />
              )}
              <Textarea
                aria-label={`Message to ${m.to ?? ''}`}
                lang={m.lang}
                className="min-h-20"
                value={m.lang === 'hi' ? (m.hi ?? '') : m.en}
                onChange={(e) => updateMsg(i, m.lang === 'hi' ? { hi: e.target.value } : { en: e.target.value })}
              />
            </div>
          ))}
          <p className="text-xs text-muted-foreground">The language shown on each message is the one that will be sent.</p>
        </div>
      )}

      {primitiveKeys.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {primitiveKeys.map((k) => (
            <Field key={k} label={k.replace(/_/g, ' ')} htmlFor={`edit-${k}`} className={k === 'title' ? 'sm:col-span-2' : undefined}>
              <Input
                id={`edit-${k}`}
                type={typeof payload[k] === 'number' ? 'number' : /date|due|_by|_on$/.test(k) && /^\d{4}-\d{2}-\d{2}$/.test(fields[k]) ? 'date' : 'text'}
                value={fields[k]}
                onChange={(e) => setFields((f) => ({ ...f, [k]: e.target.value }))}
              />
            </Field>
          ))}
        </div>
      )}

      {complexKeys.map((k) => (
        <Field key={k} label={k.replace(/_/g, ' ')} htmlFor={`edit-${k}`} error={jsonErrors[k]}>
          <Textarea
            id={`edit-${k}`}
            className="min-h-32 font-mono text-sm"
            value={json[k]}
            onChange={(e) => setJson((j) => ({ ...j, [k]: e.target.value }))}
          />
        </Field>
      ))}

      {!isMessages && primitiveKeys.length === 0 && complexKeys.length === 0 && (
        <p className="text-sm text-muted-foreground">This suggestion has nothing to edit.</p>
      )}

      <DialogFooter>
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button onClick={save} loading={busy} disabled={hasErrors}>
          Save draft
        </Button>
      </DialogFooter>
    </>
  )
}

export function RejectDialog({ finding, onClose }: { finding: Finding | null; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (!finding) return
    setBusy(true)
    try {
      await agentsStore.reject(finding, reason.trim())
      toast('Finding rejected', { description: 'Saved in History with your reason.' })
      setReason('')
      onClose()
    } catch (e) {
      toast.error('Could not reject', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={!!finding} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Reject this finding?</DialogTitle>
          <DialogDescription>{finding?.title}</DialogDescription>
        </DialogHeader>
        <Field label="Reason" htmlFor="reject-reason" hint="Helps the agent learn what is not a problem.">
          <Textarea
            id="reject-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Rate agreed by phone for urgent supply"
          />
        </Field>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={submit} loading={busy} disabled={reason.trim().length < 3}>
            Reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
