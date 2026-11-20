/**
 * Mock-mode chatbot: a tiny client-side intent router over the contract fixtures so the
 * demo questions work offline (VITE_API_MODE=mock). Mirrors the backend's deterministic
 * router in apps/api/chat/service.py. Never writes: drafts are confirmed by the user.
 */
import { api } from '@/lib/api'
import { formatINR, formatPercent } from '@/lib/format'
import type { Role } from '@/lib/role'
import type { ChatAction, ChatReplyData, Suggestion } from './types'

export const DEMO_QUESTIONS: Suggestion[] = [
  { text: 'Open JC-1301', lang: 'en' },
  { text: 'Which clients get locked this week?', lang: 'en' },
  { text: 'Why is JC-1240 flagged?', lang: 'en' },
  { text: 'Profit from Fresh Juice this month?', lang: 'en' },
  { text: 'How do I release a lock?', lang: 'en' },
  { text: 'Fresh Juice ko Hindi mein reminder likho', lang: 'hi' },
  { text: 'Record: 10 rolls PP Silver received from Vendor X', lang: 'en' },
]

const SCREENS: [RegExp, string, string][] = [
  [/\b(dashboard|home|overview)\b/, '/', 'Owner Dashboard'],
  [/\b(marketing|enquir(y|ies)|quotes?)\b/, '/marketing', 'Marketing'],
  [/\b(jobs|job cards|ppic|planning)\b/, '/jobs', 'Jobs'],
  [/\b(design|artwork|plates|dies)\b/, '/design', 'Design'],
  [/\b(store|stock|inventory|grns?|godown|maal)\b/, '/store', 'Store'],
  [/\b(production|machines?|oee|press)\b/, '/production', 'Production'],
  [/\b(qc|quality)\b/, '/qc', 'QC'],
  [/\b(dispatch|challans?|delivery)\b/, '/dispatch', 'Dispatch'],
  [/\b(money|debtors?|receivables|invoices?|payments?|collections|creditors|cash|udhaar|udhar|paisa)\b/, '/money', 'Money'],
  [/\b(agents?|findings)\b/, '/agents', 'Agents Center'],
  [/\b(floor|floor board)\b/, '/floor', 'Floor Board'],
  [/\b(settings|tolerances)\b/, '/settings', 'Settings'],
]

const JOB = /\bJC[-\s]?(\d{3,5})\b/i
const OPEN = /\b(open|go ?to|take me to|navigate to|kholo|khol|le chalo|jao)\b/i
const SHOW = /\b(show|display|view|dikhao|dikha)\b/i
const QUESTION = /\?|\b(why|how|what|which|who|when|kya|kyun|kaise|kaun|kaunse|kitna|kab)\b/i
const HINGLISH = /\b(kya|kyun|kaise|kaun|kitna|likho|batao|dikhao|kholo|mein|hai|hain|aaj|mahine|karo|chahiye|nahi|munafa)\b/i

export function isHindi(text: string): boolean {
  return /[ऀ-ॿ]/.test(text) || HINGLISH.test(text)
}

function nav(to: string): ChatAction {
  return { type: 'navigate', to }
}

function screenFor(text: string): [string, string] | null {
  for (const [rx, to, label] of SCREENS) if (rx.test(text)) return [to, label]
  return null
}

function routeNavigation(msg: string): [string, string] | null {
  const low = msg.toLowerCase()
  const job = JOB.exec(msg)
  if (OPEN.test(low) && !/\b(how|kaise)\b/.test(low)) {
    if (job) return [`/jobs/JC-${job[1]}`, `job card JC-${job[1]}`]
    return screenFor(low)
  }
  if (QUESTION.test(low)) return null
  const rest = low.replace(SHOW, ' ').replace(/\b(me|the|my|all|page|screen|list|please)\b/g, ' ').trim()
  if (rest.split(/\s+/).length <= 2) {
    if (job && /^jc[-\s]?\d+$/.test(rest)) return [`/jobs/JC-${job[1]}`, `job card JC-${job[1]}`]
    return screenFor(rest)
  }
  return null
}

/* Minimal fixture shapes used here */
interface Debtor {
  client_id: string
  client_name: string
  outstanding: number
  lock_status: string
  locks_on: string | null
}
interface ClientDetail {
  client: { id: string; name: string; contact: string; outstanding: number }
  invoices: { id: string; status: string; outstanding: number; due_date: string }[]
}
interface Cost {
  profit: number
  revenue: number
  margin_pct: number
}

async function locks(hi: boolean): Promise<ChatReplyData> {
  const d = await api.get<{ clients: Debtor[] }>('/api/debtors')
  const risk = d.clients.filter((c) => c.lock_status === 'at_risk').sort((a, b) => String(a.locks_on).localeCompare(String(b.locks_on)))
  const locked = d.clients.filter((c) => c.lock_status === 'locked')
  const lines = risk.map((c) => `- ${c.client_name}: ${formatINR(c.outstanding)}, locks on ${c.locks_on}`)
  const head = hi
    ? `${risk.length} क्लाइंट जल्द लॉक हो सकते हैं (देय तिथि + ग्रेस के बाद):`
    : `${risk.length} clients will lock soon unless they pay (due date + grace days):`
  const tail = locked.length ? `\n${hi ? 'पहले से लॉक' : 'Already locked'}: ${locked.map((c) => c.client_name).join(', ')}.` : ''
  return {
    reply: `${head}\n${lines.join('\n')}${tail}`,
    actions: [nav('/money?tab=debtors')],
    sources: [{ label: 'Debtors & lock status', link: '/money?tab=debtors' }],
  }
}

async function profit(msg: string, hi: boolean): Promise<ChatReplyData> {
  const job = JOB.exec(msg)
  const jc = job ? `JC-${job[1]}` : 'JC-1301'
  const j360 = await api.get<{ cost: Cost }>(`/api/jobs/${jc}/360`)
  const c = j360.cost
  const who = job ? jc : 'Fresh Juice Co. (JC-1301, invoiced this month)'
  const reply = hi
    ? `${who} का मुनाफ़ा ${formatINR(c.profit)} है (रेवेन्यू ${formatINR(c.revenue)}, मार्जिन ${formatPercent(c.margin_pct)})।`
    : `Profit from ${who}: ${formatINR(c.profit)} on revenue ${formatINR(c.revenue)} (margin ${formatPercent(c.margin_pct)}).`
  return { reply, actions: [nav(`/jobs/${jc}`)], sources: [{ label: `Job ${jc} 360`, link: `/jobs/${jc}` }] }
}

async function reminder(hi: boolean): Promise<ChatReplyData> {
  const d = await api.get<ClientDetail>('/api/clients/CL-001')
  const unpaid = d.invoices.filter((i) => i.status !== 'paid' && i.outstanding > 0)
  const first = unpaid[0]
  const text = hi
    ? `नमस्ते ${d.client.contact} जी, Pro Labels की ओर से विनम्र याद-दहानी: ${d.client.name} के खाते में ${formatINR(d.client.outstanding)} बकाया है${first ? ` (बिल ${first.id}, देय तिथि ${first.due_date})` : ''}। कृपया जल्द से जल्द भुगतान करें ताकि डिस्पैच बिना रुकावट चलता रहे। धन्यवाद। - अकाउंट्स, Pro Labels`
    : `Dear ${d.client.contact}, a gentle reminder from Pro Labels: ${d.client.name} has ${formatINR(d.client.outstanding)} outstanding${first ? ` (invoice ${first.id}, due ${first.due_date})` : ''}. Kindly arrange payment at the earliest. Thank you. - Accounts, Pro Labels`
  const body = {
    date: new Date().toISOString().slice(0, 10),
    client_id: d.client.id,
    invoice_ids: unpaid.map((i) => i.id),
    mode: 'whatsapp',
    contact: d.client.contact,
    note: text,
    promise_date: null,
    promise_amount: null,
    next_follow_up: null,
  }
  return {
    reply: hi ? 'रिमाइंडर का ड्राफ़्ट तैयार है। भेजने से पहले Confirm दबाएँ:' : 'Here is a draft reminder. Press Confirm to log it:',
    actions: [
      {
        type: 'draft',
        entity: 'collection',
        endpoint: '/api/collections',
        body,
        payload: body,
        text,
        summary: `Log a WhatsApp payment reminder to ${d.client.name} (${hi ? 'Hindi' : 'English'})`,
      },
    ],
    sources: [{ label: `Client ${d.client.name}`, link: `/money?tab=debtors&client=${d.client.id}` }],
  }
}

async function grn(msg: string, hi: boolean): Promise<ChatReplyData> {
  const items = await api.get<{ id: string; name: string; rate: number }[]>('/api/items')
  const rolls = Number(/(\d+)\s*rolls?/i.exec(msg)?.[1] ?? 1)
  const item = items.find((i) => /pp silver/i.test(i.name) && /pp silver/i.test(msg)) ?? items[0]
  const vendor = /\bfrom\s+(.+?)[.]?$/i.exec(msg)?.[1] ?? 'vendor'
  const lengths = Array.from({ length: rolls }, () => 1000)
  const body = {
    date: new Date().toISOString().slice(0, 10),
    vendor_id: vendor,
    bill_no: '',
    item_id: item.id,
    qty: rolls * 1000,
    rate: item.rate,
    roll_lengths_m: lengths,
  }
  const summary = `Record GRN: ${rolls} rolls ${item.name} from ${vendor} (assumes 1,000 m per roll; add the bill number)`
  return {
    reply: hi ? `GRN का ड्राफ़्ट: ${summary}। जाँचकर Confirm दबाएँ।` : `Draft GRN ready. Check it and press Confirm to save.`,
    actions: [{ type: 'draft', entity: 'grn', endpoint: '/api/store/grns', body, payload: body, summary }],
    sources: [{ label: 'Store GRNs', link: '/store?tab=grns' }],
  }
}

function howToLock(role: Role, hi: boolean): ChatReplyData {
  const reply = hi
    ? 'केवल मालिक (owner) ही लॉक हटा सकते हैं: Money > Debtors > लॉक वाला क्लाइंट चुनें > Release lock, कारण लिखें। यह समय के साथ लॉग होता है और valid-until तारीख के बाद भी बकाया रहा तो लॉक फिर लग जाता है।'
    : 'Only the owner can release a lock: Money > Debtors > pick the locked client > Release lock, and give a reason. It is logged with the time, and the lock re-applies after the valid-until date if the client still has not paid.'
  const note = role === 'owner' ? '' : hi ? `\n\nआप '${role}' के रूप में हैं, इसलिए owner से कहें।` : `\n\nYou are signed in as '${role}', so ask the owner.`
  return {
    reply: reply + note,
    actions: [nav('/money?tab=debtors')],
    sources: [
      { label: 'Pro_Labels_AI_Automation_Plan.pdf', link: null },
      { label: 'Rule: lock after due date + grace_days (15)', link: '/settings' },
    ],
  }
}

export async function mockAnswer(message: string, role: Role): Promise<ChatReplyData> {
  const msg = message.trim()
  const low = msg.toLowerCase()
  const hi = isHindi(msg)
  const route = routeNavigation(msg)
  if (route) {
    return { reply: hi ? `${route[1]} खोल रहा हूँ।` : `Opening ${route[1]}.`, actions: [nav(route[0])], sources: [] }
  }
  if (/\b(how|kaise)\b/.test(low) && /lock/.test(low)) return howToLock(role, hi)
  if (/\b(release|unlock|hatao)\b/.test(low) && /lock/.test(low)) {
    if (role !== 'owner') {
      return { reply: hi ? 'केवल मालिक (owner) ही क्लाइंट का लॉक हटा सकते हैं।' : `Only the owner can release a client lock. You are signed in as '${role}'.`, actions: [nav('/money?tab=debtors')], sources: [] }
    }
    return howToLock(role, hi)
  }
  if (/\b(remind|reminder|yaad)\b/.test(low)) return reminder(hi || /\bhindi\b/i.test(msg))
  if (/\b(record|grn|received|aaya)\b/.test(low) && /\d/.test(low)) return grn(msg, hi)
  if (JOB.test(msg) && /\b(why|flag|flagged|wastage|kyun|problem)\b/.test(low)) {
    const fixture = await api.post<ChatReplyData>('/api/chat', { message: msg, role })
    if (/JC-1240/i.test(msg)) return fixture
  }
  if (/\b(profit|margin|munafa)\b/.test(low)) return profit(msg, hi)
  if (/\b(lock|locked|at.risk|debtors?|overdue)\b/.test(low)) return locks(hi)
  if (JOB.test(msg)) {
    const jc = `JC-${JOB.exec(msg)![1]}`
    return { reply: hi ? `${jc} खोल रहा हूँ।` : `Here is ${jc}.`, actions: [nav(`/jobs/${jc}`)], sources: [] }
  }
  return {
    reply: hi
      ? 'डेमो मोड में मैं ये कर सकता हूँ: स्क्रीन या जॉब कार्ड खोलना, लॉक होने वाले क्लाइंट, फ़्लैग की वजह, मुनाफ़ा, रिमाइंडर और GRN ड्राफ़्ट।'
      : 'In demo mode I can open screens and job cards, list clients about to lock, explain a flagged job, show profit, and draft reminders or GRNs. Try one of the suggestions.',
    actions: [],
    sources: [],
  }
}
