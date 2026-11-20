import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { ArrowRight, CornerDownLeft, FileText, Loader2, Search } from 'lucide-react'
import { api, withQuery } from '@/lib/api'
import { useRole } from '@/lib/role'
import { cn } from '@/lib/utils'
import { DialogOverlay, DialogPortal, Kbd } from '@/components/ui'
import { NAV_ITEMS, canSee } from './nav'

interface SearchHit {
  label: string
  sub?: string
  to: string
  kind?: string
}

/** Normalise whatever /api/search returns into hits with a link. */
function toHits(raw: unknown): SearchHit[] {
  const list: unknown[] = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object'
      ? ((raw as Record<string, unknown>).results ??
          (raw as Record<string, unknown>).items ??
          (raw as Record<string, unknown>).hits ??
          []) as unknown[]
      : []
  if (!Array.isArray(list)) return []
  const out: SearchHit[] = []
  for (const r of list) {
    if (!r || typeof r !== 'object') continue
    const o = r as Record<string, unknown>
    const id = String(o.id ?? o.job_card ?? '')
    const kind = String(o.type ?? o.kind ?? o.entity ?? '')
    const label = String(o.title ?? o.label ?? o.name ?? id)
    const sub = o.subtitle ?? o.description ?? o.sub ?? o.client ?? undefined
    let to = String(o.link ?? o.url ?? o.path ?? o.to ?? '')
    if (!to) {
      if (/^JC-/i.test(id) || kind === 'job') to = `/jobs/${id}`
      else if (kind === 'client' || kind === 'invoice') to = '/money'
      else if (kind === 'item') to = '/store'
      else if (kind === 'enquiry' || kind === 'quote') to = '/marketing'
      else to = '/'
    }
    if (label) out.push({ label, sub: sub ? String(sub) : undefined, to, kind: kind || undefined })
  }
  return out
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate()
  const role = useRole()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  // Reset when opened
  useEffect(() => {
    if (open) {
      setQ('')
      setHits([])
      setActive(0)
    }
  }, [open])

  // Debounced fixture / API search
  useEffect(() => {
    const term = q.trim()
    if (!open || term.length < 2) {
      setHits([])
      setSearching(false)
      return
    }
    let alive = true
    setSearching(true)
    const t = setTimeout(() => {
      api
        .get<unknown>(withQuery('/api/search', { q: term }))
        .then((raw) => {
          if (!alive) return
          let found = toHits(raw)
          if (api.mode === 'mock') {
            const needle = term.toLowerCase()
            found = found.filter((h) => `${h.label} ${h.sub ?? ''} ${h.kind ?? ''}`.toLowerCase().includes(needle))
          }
          setHits(found.slice(0, 8))
        })
        .catch(() => alive && setHits([]))
        .finally(() => alive && setSearching(false))
    }, 180)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [q, open])

  const pages = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return NAV_ITEMS.filter((i) => canSee(i, role)).filter(
      (i) => !needle || `${i.title} ${i.description} ${i.keywords ?? ''}`.toLowerCase().includes(needle),
    )
  }, [q, role])

  const entries = useMemo(
    () => [
      ...hits.map((h) => ({ kind: 'hit' as const, key: `h-${h.to}-${h.label}`, to: h.to, hit: h })),
      ...pages.map((p) => ({ kind: 'page' as const, key: `p-${p.to}`, to: p.to, page: p })),
    ],
    [hits, pages],
  )

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, entries.length - 1)))
  }, [entries.length])

  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const go = (to: string) => {
    onOpenChange(false)
    navigate(to)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (entries.length ? (a + 1) % entries.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (entries.length ? (a - 1 + entries.length) % entries.length : 0))
    } else if (e.key === 'Enter') {
      const entry = entries[active]
      if (entry) {
        e.preventDefault()
        go(entry.to)
      }
    }
  }

  let idx = -1
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content
          onKeyDown={onKeyDown}
          className="fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-surface shadow-lg data-[state=open]:animate-[dialog-in_140ms_ease-out]"
        >
          <DialogPrimitive.Title className="sr-only">Search and jump</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Search jobs, clients and items, or jump to a page.
          </DialogPrimitive.Description>
          <div className="flex items-center gap-3 border-b border-border px-4">
            {searching ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
            ) : (
              <Search className="size-4 shrink-0 text-muted-foreground" />
            )}
            <input
              autoFocus
              value={q}
              onChange={(e) => {
                setQ(e.target.value)
                setActive(0)
              }}
              placeholder="Search job, client or item…"
              aria-label="Search job, client or item"
              className="h-12 flex-1 bg-transparent text-md text-foreground outline-none placeholder:text-subtle-foreground focus-visible:outline-none"
            />
            <Kbd>Esc</Kbd>
          </div>

          <div ref={listRef} className="max-h-[min(60vh,420px)] overflow-y-auto p-2" role="listbox">
            {hits.length > 0 && (
              <div className="pb-2">
                <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">Results</div>
                {hits.map((h) => {
                  idx++
                  const i = idx
                  return (
                    <PaletteRow key={`h-${h.to}-${h.label}-${i}`} active={active === i} onHover={() => setActive(i)} onClick={() => go(h.to)}>
                      <FileText className="size-4 text-subtle-foreground" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-base font-medium text-foreground">{h.label}</div>
                        {h.sub && <div className="truncate text-xs text-muted-foreground">{h.sub}</div>}
                      </div>
                      {h.kind && <span className="text-xs text-subtle-foreground capitalize">{h.kind}</span>}
                    </PaletteRow>
                  )
                })}
              </div>
            )}
            {pages.length > 0 && (
              <div>
                <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">Go to</div>
                {pages.map((p) => {
                  idx++
                  const i = idx
                  const Icon = p.icon
                  return (
                    <PaletteRow key={p.to} active={active === i} onHover={() => setActive(i)} onClick={() => go(p.to)}>
                      <Icon className="size-4 text-subtle-foreground" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-base font-medium text-foreground">{p.title}</div>
                        <div className="truncate text-xs text-muted-foreground">{p.description}</div>
                      </div>
                      <ArrowRight className="size-3.5 text-subtle-foreground opacity-0 group-data-[active=true]:opacity-100" />
                    </PaletteRow>
                  )
                })}
              </div>
            )}
            {entries.length === 0 && !searching && (
              <div className="px-4 py-10 text-center text-sm text-muted-foreground">
                No matches for “{q}”. Try a job card like JC-1001 or a client name.
              </div>
            )}
          </div>
          <div className="flex items-center gap-4 border-t border-border bg-surface-muted px-4 py-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> to move
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>
                <CornerDownLeft className="size-3" />
              </Kbd>
              to open
            </span>
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </DialogPrimitive.Root>
  )
}

function PaletteRow({
  active,
  onHover,
  onClick,
  children,
}: {
  active: boolean
  onHover: () => void
  onClick: () => void
  children: ReactNode
}) {
  return (
    <div
      role="option"
      aria-selected={active}
      data-active={active}
      onMouseMove={onHover}
      onClick={onClick}
      className={cn(
        'group flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2',
        active ? 'bg-surface-muted' : 'hover:bg-surface-muted',
      )}
    >
      {children}
    </div>
  )
}
