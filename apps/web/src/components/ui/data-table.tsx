import { useMemo, useState, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { EmptyState } from './empty-state'
import { TableSkeleton } from './skeleton'

export interface Column<T> {
  /** Unique key; also the default field read for display/sort. */
  key: string
  header: ReactNode
  /** Custom cell. Default: String(row[key]). */
  cell?: (row: T) => ReactNode
  /** Value used for sorting. Default: row[key]. Set `sortable: false` to disable. */
  sortValue?: (row: T) => string | number | null | undefined
  sortable?: boolean
  align?: 'left' | 'right' | 'center'
  /** Tailwind width class, e.g. 'w-32' */
  width?: string
  className?: string
}

export interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[] | undefined
  /** Stable row key. Default: row.id ?? index */
  rowKey?: (row: T, index: number) => string | number
  onRowClick?: (row: T) => void
  loading?: boolean
  empty?: ReactNode
  /** Initial sort */
  defaultSort?: { key: string; dir: 'asc' | 'desc' }
  /** Max height for the scroll area (sticky header). Default: none (page scroll). */
  maxHeight?: number | string
  className?: string
  /** Dense rows for big registers */
  dense?: boolean
}

function readField<T>(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function compare(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), 'en-IN', { numeric: true, sensitivity: 'base' })
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  loading,
  empty,
  defaultSort,
  maxHeight,
  className,
  dense,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(defaultSort ?? null)

  const sorted = useMemo(() => {
    if (!rows) return []
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col) return rows
    const get = col.sortValue ?? ((r: T) => readField(r, col.key))
    const out = [...rows].sort((a, b) => compare(get(a), get(b)))
    return sort.dir === 'desc' ? out.reverse() : out
  }, [rows, sort, columns])

  const toggleSort = (key: string) =>
    setSort((s) => (s?.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null))

  const cellPad = dense ? 'px-4 py-2' : 'px-4 py-3'

  return (
    <div
      className={cn('relative overflow-auto rounded-lg border border-border bg-surface', className)}
      style={maxHeight ? { maxHeight } : undefined}
    >
      <table className="w-full border-separate border-spacing-0 text-base">
        <thead>
          <tr>
            {columns.map((col) => {
              const sortable = col.sortable !== false
              const active = sort?.key === col.key
              const SortIcon = active ? (sort!.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  className={cn(
                    'sticky top-0 z-10 border-b border-border bg-surface-muted text-xs font-medium whitespace-nowrap text-muted-foreground',
                    dense ? 'px-4 py-2' : 'px-4 py-2.5',
                    col.align === 'right' && 'text-right',
                    col.align === 'center' && 'text-center',
                    col.width,
                  )}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-sm hover:text-foreground',
                        active && 'text-foreground',
                        col.align === 'right' && 'flex-row-reverse',
                      )}
                    >
                      {col.header}
                      <SortIcon className={cn('size-3', !active && 'opacity-40')} aria-hidden />
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading && !rows ? (
            <tr>
              <td colSpan={columns.length} className="p-0">
                <TableSkeleton columns={Math.min(columns.length, 6)} />
              </td>
            </tr>
          ) : sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>
                {empty ?? <EmptyState compact title="Nothing to show" description="No rows match right now." />}
              </td>
            </tr>
          ) : (
            sorted.map((row, i) => (
              <tr
                key={rowKey ? rowKey(row, i) : ((readField(row, 'id') as string | number | undefined) ?? i)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === 'Enter') onRowClick(row)
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  'group transition-colors',
                  onRowClick && 'cursor-pointer hover:bg-surface-muted focus-visible:bg-surface-muted',
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      'border-b border-border text-foreground group-last:border-b-0',
                      cellPad,
                      col.align === 'right' && 'tabular text-right',
                      col.align === 'center' && 'text-center',
                      col.className,
                    )}
                  >
                    {col.cell ? col.cell(row) : String(readField(row, col.key) ?? '—')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
