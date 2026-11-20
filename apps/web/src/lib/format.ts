/**
 * Number / money / date formatting for an Indian audience.
 * All money uses en-IN grouping (12,34,567) and lakh / crore abbreviations.
 */

const LAKH = 1_00_000
const CRORE = 1_00_00_000

const inrFull = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const inrWhole = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

const intIN = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function trimDecimals(n: number, digits: number): string {
  return n.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
}

/** Full rupees with paise: `₹35,400.00`. */
export function formatINR(value: number | null | undefined): string {
  if (!isNum(value)) return '—'
  return inrFull.format(value)
}

/** Whole rupees with Indian grouping: `₹35,400`. */
export function formatINRWhole(value: number | null | undefined): string {
  if (!isNum(value)) return '—'
  return inrWhole.format(value)
}

/**
 * Short rupees: `₹2.32 Cr`, `₹4.2 L`, `₹85.4 K`, `₹950`.
 * @param digits max decimals (default 2 for Cr, 1 for L / K)
 */
export function formatINRShort(value: number | null | undefined, digits?: number): string {
  if (!isNum(value)) return '—'
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (abs >= CRORE) return `${sign}₹${trimDecimals(abs / CRORE, digits ?? 2)} Cr`
  if (abs >= LAKH) return `${sign}₹${trimDecimals(abs / LAKH, digits ?? 1)} L`
  if (abs >= 1_000) return `${sign}₹${trimDecimals(abs / 1_000, digits ?? 1)} K`
  return `${sign}₹${intIN.format(abs)}`
}

/** Plain number with Indian grouping: `12,34,567`. */
export function formatNumber(value: number | null | undefined, maxDigits = 0): string {
  if (!isNum(value)) return '—'
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: maxDigits }).format(value)
}

/** Compact number in lakh / crore: `4.2 L`, `1.1 Cr`, `12.5 K`, `850`. */
export function formatCompact(value: number | null | undefined): string {
  if (!isNum(value)) return '—'
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (abs >= CRORE) return `${sign}${trimDecimals(abs / CRORE, 2)} Cr`
  if (abs >= LAKH) return `${sign}${trimDecimals(abs / LAKH, 1)} L`
  if (abs >= 1_000) return `${sign}${trimDecimals(abs / 1_000, 1)} K`
  return `${sign}${intIN.format(abs)}`
}

/**
 * Percent from a ratio: `formatPercent(0.153)` -> `15.3%`.
 * Pass `{ signed: true }` for deltas: `+4.2%` / `-1.0%`.
 */
export function formatPercent(
  ratio: number | null | undefined,
  opts: { digits?: number; signed?: boolean } = {},
): string {
  if (!isNum(ratio)) return '—'
  const digits = opts.digits ?? 1
  const pct = ratio * 100
  const body = `${Math.abs(pct).toFixed(digits)}%`
  if (opts.signed) return `${pct > 0 ? '+' : pct < 0 ? '-' : ''}${body}`
  return `${pct < 0 ? '-' : ''}${body}`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Parse ISO `YYYY-MM-DD` as a local date (no timezone shift); other strings via Date. */
export function parseDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/** `21 Nov 2026`. */
export function formatDate(value: string | Date | null | undefined): string {
  const d = parseDate(value)
  if (!d) return '—'
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

/** `21 Nov`. */
export function formatDateShort(value: string | Date | null | undefined): string {
  const d = parseDate(value)
  if (!d) return '—'
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

/** `21 Nov 2026, 14:05`. */
export function formatDateTime(value: string | Date | null | undefined): string {
  const d = parseDate(value)
  if (!d) return '—'
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${formatDate(d)}, ${hh}:${mm}`
}

/** `Nov 2026` from `2026-11` or a date. */
export function formatMonth(value: string | Date | null | undefined): string {
  if (typeof value === 'string' && /^\d{4}-\d{2}$/.test(value)) {
    const [y, m] = value.split('-')
    return `${MONTHS[Number(m) - 1]} ${y}`
  }
  const d = parseDate(value)
  if (!d) return '—'
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

/** `5 min ago`, `3 h ago`, `2 d ago`, else the date. */
export function formatRelative(value: string | Date | null | undefined, now: Date = new Date()): string {
  const d = parseDate(value)
  if (!d) return '—'
  const s = Math.round((now.getTime() - d.getTime()) / 1000)
  if (s < 0) return formatDate(d)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`
  return formatDate(d)
}
