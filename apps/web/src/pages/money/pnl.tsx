import { useState } from 'react'
import { CheckCircle2, Info } from 'lucide-react'
import type { Pnl } from '@contract/types'
import { QueryState, Segmented, StatusChip } from '@/components/ui'
import { useApi, withQuery } from '@/lib/api'
import { formatDateTime, formatINR, formatINRShort, formatMonth } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Stat } from './shared'

/** Last few closed months, newest first (Tally is imported after month end). */
function recentMonths(n: number, from?: string | null): string[] {
  const base = from && /^\d{4}-\d{2}$/.test(from) ? from : '2026-10'
  let [y, m] = base.split('-').map(Number)
  const out: string[] = []
  for (let i = 0; i < n; i++) {
    out.push(`${y}-${String(m).padStart(2, '0')}`)
    m -= 1
    if (m === 0) {
      m = 12
      y -= 1
    }
  }
  return out
}

export function PnlTab({ initialMonth }: { initialMonth?: string | null }) {
  const months = recentMonths(3)
  const [month, setMonth] = useState<string>(initialMonth && /^\d{4}-\d{2}$/.test(initialMonth) ? initialMonth : months[0])
  const q = useApi<Pnl>(withQuery('/api/pnl', { month }))
  const options = months.includes(month) ? months : [month, ...months]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">Profit from this system compared with your Tally books, line by line.</p>
        <Segmented
          aria-label="Month"
          value={month}
          onChange={setMonth}
          options={options.map((m) => ({ value: m, label: formatMonth(m) }))}
        />
      </div>
      <QueryState query={q} isEmpty={(d) => d.lines.length === 0}>
        {(p) => (
          <div className="space-y-4">
            {p.month !== month && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Info className="size-4" aria-hidden />
                No P&amp;L for {formatMonth(month)} yet; showing {formatMonth(p.month)}.
              </p>
            )}
            <div className="grid grid-cols-2 gap-4 rounded-lg border border-border bg-surface p-5 lg:grid-cols-4">
              <Stat label={`System profit · ${formatMonth(p.month)}`} value={formatINRShort(p.system_profit)} />
              <Stat label="Tally profit" value={formatINRShort(p.tally_profit)} />
              <Stat
                label="Difference"
                value={formatINRShort(p.difference)}
                tone={Math.abs(p.difference) > 0.5 ? 'warn' : 'ok'}
              />
              <div>
                <div className="text-xs font-medium text-muted-foreground">Status</div>
                <div className="mt-2">
                  {p.matched ? (
                    <StatusChip tone="ok">
                      <CheckCircle2 className="size-3" aria-hidden /> Matched
                    </StatusChip>
                  ) : (
                    <StatusChip tone="warn">Needs review</StatusChip>
                  )}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Tally imported {p.tally_imported_at ? formatDateTime(p.tally_imported_at) : '—'}
                </div>
              </div>
            </div>

            <div className="overflow-x-auto rounded-lg border border-border bg-surface">
              <table className="w-full min-w-[720px] text-base">
                <thead>
                  <tr className="bg-surface-muted text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 text-left font-medium">Line</th>
                    <th className="px-4 py-2.5 text-right font-medium">System</th>
                    <th className="px-4 py-2.5 text-right font-medium">Tally</th>
                    <th className="px-4 py-2.5 text-right font-medium">Difference</th>
                    <th className="px-4 py-2.5 text-left font-medium">Why</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {p.lines.map((l) => {
                    const off = Math.abs(l.diff) > 0.5
                    const total = l.key === 'profit'
                    return (
                      <tr
                        key={l.key}
                        className={cn('border-t border-border', total && 'border-t-2 border-border-strong font-semibold', off && !total && 'bg-warn-soft/50')}
                      >
                        <td className="px-4 py-2.5">{l.label}</td>
                        <td className="px-4 py-2.5 text-right">{formatINR(l.system)}</td>
                        <td className="px-4 py-2.5 text-right">{formatINR(l.tally)}</td>
                        <td className={cn('px-4 py-2.5 text-right', off ? 'font-medium text-warn-foreground' : 'text-muted-foreground')}>
                          {off ? formatINR(l.diff) : 'Matches'}
                        </td>
                        <td className="px-4 py-2.5 text-sm text-muted-foreground">{l.note || (off ? 'Not explained yet' : '')}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted-foreground">Difference = System − Tally. Costs higher in Tally show as a negative difference.</p>
          </div>
        )}
      </QueryState>
    </div>
  )
}
