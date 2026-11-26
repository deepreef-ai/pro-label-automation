import { NavLink } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useRole } from '@/lib/role'
import { DEFAULT_COMPANY, initials, useSession } from '@/lib/session'
import { Tooltip } from '@/components/ui'
import { navForRole } from './nav'

export function Logo({ collapsed }: { collapsed?: boolean }) {
  const company = useSession()?.company ?? DEFAULT_COMPANY
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground shadow-xs">
        {company.id === DEFAULT_COMPANY.id ? (
          <svg viewBox="0 0 32 32" className="size-5" aria-hidden>
          <path d="M10 8h7.5a5.5 5.5 0 0 1 0 11H14v5h-4z" fill="currentColor" />
          <path d="M14 12v3h3.3a1.5 1.5 0 0 0 0-3z" className="fill-accent" />
          </svg>
        ) : (
          <span className="text-md font-bold">{initials(company.name)}</span>
        )}
      </span>
      {!collapsed && (
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-md font-semibold tracking-tight whitespace-nowrap text-foreground">{company.name}</span>
          <span className="rounded-sm bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold tracking-wide whitespace-nowrap text-accent-soft-foreground uppercase">
            AI Ops
          </span>
        </div>
      )}
    </div>
  )
}

export function SidebarNav({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const role = useRole()
  const groups = navForRole(role)
  return (
    <nav aria-label="Main" className="flex flex-col gap-5">
      {groups.map((group, gi) => (
        <div key={group.label ?? `g${gi}`} className="flex flex-col gap-0.5">
          {group.label && !collapsed && (
            <div className="px-3 pb-1.5 text-[11px] font-medium tracking-wider text-subtle-foreground uppercase">
              {group.label}
            </div>
          )}
          {group.label === null && <div className="mx-3 mb-2 h-px bg-border" aria-hidden />}
          {group.items.map((item) => {
            const Icon = item.icon
            const link = (
              <NavLink
                to={item.to}
                end={item.to === '/'}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    'group relative flex h-9 items-center gap-3 rounded-md px-3 text-base font-medium transition-colors',
                    collapsed && 'justify-center px-0',
                    isActive
                      ? 'bg-surface text-foreground shadow-xs ring-1 ring-border'
                      : 'text-muted-foreground hover:bg-surface-muted hover:text-foreground',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon
                      className={cn('size-[18px] shrink-0', isActive ? 'text-accent' : 'text-subtle-foreground group-hover:text-foreground')}
                      strokeWidth={1.9}
                      aria-hidden
                    />
                    {collapsed ? <span className="sr-only">{item.title}</span> : <span className="truncate">{item.title}</span>}
                  </>
                )}
              </NavLink>
            )
            return collapsed ? (
              <Tooltip key={item.to} content={item.title} side="right">
                {link}
              </Tooltip>
            ) : (
              <div key={item.to}>{link}</div>
            )
          })}
        </div>
      ))}
    </nav>
  )
}

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-border bg-surface-muted/60 backdrop-blur lg:flex',
        'transition-[width] duration-200 ease-out',
      )}
      style={{ width: collapsed ? 'var(--sidebar-collapsed)' : 'var(--sidebar-width)' }}
    >
      <div className={cn('flex h-[var(--topbar-height)] shrink-0 items-center', collapsed ? 'justify-center px-2' : 'px-5')}>
        <NavLink to="/" aria-label="Home" className="rounded-md">
          <Logo collapsed={collapsed} />
        </NavLink>
      </div>
      <div className={cn('flex-1 overflow-y-auto pt-2 pb-4', collapsed ? 'px-2' : 'px-3')}>
        <SidebarNav collapsed={collapsed} />
      </div>
      <div className={cn('shrink-0 border-t border-border py-3', collapsed ? 'px-2' : 'px-3')}>
        <Tooltip content={collapsed ? 'Expand sidebar' : null} side="right">
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cn(
              'flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface hover:text-foreground',
              collapsed && 'justify-center px-0',
            )}
          >
            {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
            {!collapsed && 'Collapse'}
          </button>
        </Tooltip>
      </div>
    </aside>
  )
}
