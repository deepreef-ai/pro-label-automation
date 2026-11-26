import { Building2, Check, ChevronDown, Cloud, Cpu, LogIn, LogOut, Menu, Moon, Search, Sun, UserRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useApi, useSampleDataShown } from '@/lib/api'
import { ROLES, ROLE_LABELS, setRole, useRole, type Role } from '@/lib/role'
import { signOut, useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DemoBadge,
  DropdownMenuTrigger,
  Kbd,
  Tooltip,
  toast,
} from '@/components/ui'
import { useTheme } from './theme'
import { FeedbackDialog } from './FeedbackDialog'

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

function AiModePill() {
  const { data } = useApi<{ ai_mode?: string }>('/api/settings')
  const local = (data?.ai_mode ?? 'cloud').toLowerCase() === 'local'
  const Icon = local ? Cpu : Cloud
  return (
    <Tooltip content={local ? 'AI runs on this computer (Ollama). Change in Settings.' : 'AI uses free cloud models. Change in Settings.'}>
      <span
        tabIndex={0}
        className="hidden h-8 items-center gap-1.5 rounded-full border border-border bg-surface px-3 text-sm font-medium text-muted-foreground sm:inline-flex"
      >
        <span className={cn('size-1.5 rounded-full', local ? 'bg-info' : 'bg-ok')} aria-hidden />
        <Icon className="size-3.5" aria-hidden />
        AI: {local ? 'Local' : 'Cloud'}
      </span>
    </Tooltip>
  )
}

/** Live mode: some data on screen is sample data because the backend lacks that endpoint yet. */
function SampleDataPill() {
  const shown = useSampleDataShown()
  return (
    <DemoBadge
      show={shown}
      label="Sample data"
      title="Part of this screen uses sample data: the live backend does not serve that endpoint yet."
      className="hidden sm:inline-flex"
    />
  )
}

function RoleSwitcher() {
  const role = useRole()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" size="sm" aria-label={`Role: ${ROLE_LABELS[role]}. Change role`} className="gap-2 pr-2">
          <span className="flex size-5 items-center justify-center rounded-full bg-accent-soft text-accent-soft-foreground">
            <UserRound className="!size-3" />
          </span>
          <span className="hidden sm:inline">{ROLE_LABELS[role]}</span>
          <ChevronDown className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>View the app as…</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={role}
          onValueChange={(v) => {
            setRole(v as Role)
            toast(`Now viewing as ${ROLE_LABELS[v as Role]}`, { icon: <Check className="size-4" /> })
          }}
        >
          {ROLES.map((r) => (
            <DropdownMenuRadioItem key={r} value={r}>
              {ROLE_LABELS[r]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Signed in: company badge + menu (user, role, sign out). The role comes from the login, so no switcher. */
function CompanyMenu() {
  const session = useSession()
  const navigate = useNavigate()
  if (!session) return null
  const role = session.role === 'platform_admin' ? 'Platform admin' : ROLE_LABELS[session.role as Role]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="secondary"
          size="sm"
          aria-label={`${session.company.name}, signed in as ${role}. Account menu`}
          className="gap-2 border-accent/40 bg-accent-soft pr-2 text-accent-soft-foreground hover:bg-accent-soft"
        >
          <Building2 aria-hidden />
          <span className="hidden max-w-40 truncate sm:inline">{session.company.name}</span>
          <span className="hidden text-xs font-normal opacity-80 md:inline">· {role}</span>
          <ChevronDown className="opacity-70" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="space-y-0.5">
          <div className="text-sm font-semibold text-foreground">{session.company.name}</div>
          <div className="text-xs font-normal text-muted-foreground">
            {session.user.login || session.user.name} · {role}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <p className="px-2 py-1.5 text-xs text-muted-foreground">You see only {session.company.name} data.</p>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => {
            signOut()
            toast('Signed out')
            navigate('/login', { replace: true })
          }}
        >
          <LogOut className="mr-2 size-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Not signed in (demo v0.1 behaviour): a quiet link to the company sign-in. */
function SignInLink() {
  const navigate = useNavigate()
  return (
    <Tooltip content="Sign in to a company">
      <Button variant="ghost" size="sm" onClick={() => navigate('/login')} className="gap-1.5">
        <LogIn /> <span className="hidden md:inline">Sign in</span>
      </Button>
    </Tooltip>
  )
}

export function Topbar({ onOpenSearch, onOpenMobileNav }: { onOpenSearch: () => void; onOpenMobileNav: () => void }) {
  const { theme, toggle } = useTheme()
  const session = useSession()
  return (
    <header className="sticky top-0 z-20 flex h-[var(--topbar-height)] items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur-md sm:px-6">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={onOpenMobileNav} aria-label="Open menu">
        <Menu />
      </Button>

      <button
        type="button"
        onClick={onOpenSearch}
        className="group flex h-9 w-full max-w-md min-w-0 items-center gap-2.5 rounded-md border border-border bg-surface px-3 text-left text-base text-subtle-foreground shadow-xs transition-colors hover:border-border-strong"
      >
        <Search className="size-4 shrink-0" aria-hidden />
        <span className="flex-1 truncate">Search job, client or item…</span>
        <span className="hidden items-center gap-1 sm:flex">
          <Kbd>{isMac ? '⌘' : 'Ctrl'}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      <div className="ml-auto flex items-center gap-2">
        <SampleDataPill />
        <AiModePill />
        <FeedbackDialog />
        <Tooltip content={theme === 'dark' ? 'Light mode' : 'Dark mode'}>
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle dark mode">
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
        </Tooltip>
        {session ? (
          <CompanyMenu />
        ) : (
          <>
            <SignInLink />
            <RoleSwitcher />
          </>
        )}
      </div>
    </header>
  )
}
