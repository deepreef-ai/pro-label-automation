import { useEffect, useState, type FormEvent } from 'react'
import { Building2, Mail, MessageCircle, Plug, ShieldCheck, UserPlus, Users } from 'lucide-react'
import type { CompanyProfile, CompanyUser, CompanyUserList, Connection, ConnectionList, UserInvite } from '@contract/types'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  Input,
  PageHeader,
  QueryState,
  Select,
  StatusChip,
  toast,
  type Column,
} from '@/components/ui'
import { api, useApi } from '@/lib/api'
import { formatDate, formatINRWhole, formatPercent, formatRelative } from '@/lib/format'
import { ROLES, ROLE_LABELS, useRole, type Role } from '@/lib/role'
import { APP_DOMAIN, currentCompany } from '@/lib/session'
import { BudgetBar } from '@/pages/platform/shared'

/**
 * Screen 19 · Company admin: Users & connections (W3 #58). The company owner is its admin (contract §6.2);
 * everything here belongs to the signed-in company only.
 */
export default function CompanyAdminPage() {
  const role = useRole()
  if (role !== 'owner') {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="Company admin only"
        description="Users and connections are managed by your company's owner."
      />
    )
  }
  return <CompanyAdmin />
}

const ROLE_OPTIONS = ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] }))
const SIGN_IN: Record<CompanyUser['sign_in'], string> = { otp_phone: 'OTP · phone', otp_email: 'OTP · e-mail' }
const USER_TONE = { active: 'ok', invited: 'info', disabled: 'neutral' } as const
const CONN_TONE = { connected: 'ok', demo: 'info', not_connected: 'neutral', error: 'danger' } as const
const CONN_LABEL = { connected: 'Connected', demo: 'Demo', not_connected: 'Not connected', error: 'Error' } as const
const CONN_ICON = { erp: Plug, tally: Building2, po_inbox: Mail, whatsapp: MessageCircle } as const

function CompanyAdmin() {
  const company = currentCompany()
  const profile = useApi<CompanyProfile>('/api/company/profile')
  const usersQ = useApi<CompanyUserList>('/api/company/users')
  const conns = useApi<ConnectionList>('/api/company/connections')
  // Local copy so invites and edits show at once (mock mode echoes; live refetches).
  const [users, setUsers] = useState<CompanyUser[] | undefined>(undefined)
  const [inviteOpen, setInviteOpen] = useState(false)
  useEffect(() => setUsers(usersQ.data?.items), [usersQ.data])

  async function updateUser(u: CompanyUser, patch: Partial<Pick<CompanyUser, 'role' | 'status'>>) {
    try {
      await api.put<CompanyUser>(`/api/company/users/${u.id}`, patch)
      setUsers((list) => list?.map((x) => (x.id === u.id ? { ...x, ...patch } : x)))
      toast.success(
        patch.status === 'disabled'
          ? `${u.name} can no longer sign in`
          : patch.status === 'active'
            ? `${u.name} can sign in again`
            : `${u.name} is now ${ROLE_LABELS[patch.role as Role]}`,
      )
    } catch (e) {
      toast.error((e as Error).message || 'Could not update the user')
    }
  }

  const columns: Column<CompanyUser>[] = [
    {
      key: 'name',
      header: 'User',
      sortValue: (u) => u.name,
      cell: (u) => (
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-bold text-accent-soft-foreground">
            {u.name.charAt(0)}
          </span>
          <div className="min-w-0">
            <div className="truncate font-medium">{u.name}</div>
            <div className="truncate text-xs text-muted-foreground">{u.login}</div>
          </div>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      sortValue: (u) => u.role,
      cell: (u) =>
        u.role === 'owner' ? (
          <span className="text-sm">Owner (admin)</span>
        ) : (
          <Select
            size="sm"
            aria-label={`Role of ${u.name}`}
            value={u.role}
            options={ROLE_OPTIONS.filter((o) => o.value !== 'owner')}
            onValueChange={(v) => void updateUser(u, { role: v as Role })}
            className="w-36"
          />
        ),
    },
    { key: 'device', header: 'Device', cell: (u) => u.device ?? '—' },
    { key: 'sign_in', header: 'Sign-in', cell: (u) => SIGN_IN[u.sign_in] ?? u.sign_in },
    {
      key: 'last',
      header: 'Last active',
      sortValue: (u) => u.last_active_at ?? '',
      cell: (u) => (u.last_active_at ? formatRelative(u.last_active_at) : '—'),
    },
    {
      key: 'status',
      header: 'Status',
      sortValue: (u) => u.status,
      cell: (u) => <StatusChip tone={USER_TONE[u.status]}>{u.status.charAt(0).toUpperCase() + u.status.slice(1)}</StatusChip>,
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      cell: (u) =>
        u.role === 'owner' ? null : u.status === 'disabled' ? (
          <Button size="sm" variant="ghost" onClick={() => void updateUser(u, { status: 'active' })}>
            Enable
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => void updateUser(u, { status: 'disabled' })}>
            Disable
          </Button>
        ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users & connections"
        subtitle={`Managed by ${company.name}'s company admin. These users and links belong to ${company.name} only.`}
        actions={
          <Button onClick={() => setInviteOpen(true)}>
            <UserPlus /> Invite user
          </Button>
        }
      />

      <div className="space-y-4">
        <Card>
          <CardHeader
            title="Users"
            description={
              usersQ.data
                ? `${usersQ.data.totals.active} active · ${usersQ.data.totals.invited} invited · ${usersQ.data.totals.disabled} disabled`
                : undefined
            }
          />
          <QueryState query={usersQ}>
            {() => <DataTable columns={columns} rows={users} rowKey={(u) => u.id} defaultSort={{ key: 'name', dir: 'asc' }} />}
          </QueryState>
          <CardContent className="pt-3 text-xs text-muted-foreground">
            The role decides screens and actions (e.g. Store cannot edit invoices). Only the owner changes limits or releases a
            locked client. Every change is in the audit log.
          </CardContent>
        </Card>

        <div className="grid items-start gap-4 lg:grid-cols-3">
          <QueryState query={profile}>
            {(p) => (
              <>
                <Card>
                  <CardHeader title="Company profile" description="Shown on invoices, challans and the login page." />
                  <CardContent className="space-y-2 text-sm">
                    <KV k="Name" v={p.name} />
                    <KV k="Web address" v={`${p.slug}.${APP_DOMAIN}`} />
                    <KV k="GSTIN" v={p.gstin ?? '—'} />
                    <KV k="City" v={[p.city, p.state].filter(Boolean).join(', ') || '—'} />
                    <KV k="Plan" v={`${p.plan} · shared, isolated database`} />
                    <KV k="Since" v={formatDate(p.created_on)} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader
                    title="AI budget"
                    description={`Alarm at ${formatPercent(p.ai_alert_pct, { digits: 0 })}; at 100% AI features use their non-AI fallback.`}
                    actions={p.ai_over_budget ? <Badge tone="danger">Over budget</Badge> : undefined}
                  />
                  <CardContent className="space-y-1.5">
                    <BudgetBar pct={p.ai_used_pct} className="w-full" />
                    <div className="text-sm text-muted-foreground">
                      {formatINRWhole(p.ai_used_month)} used of {formatINRWhole(p.ai_budget_month)} this month (
                      {formatPercent(p.ai_used_pct, { digits: 0 })})
                    </div>
                  </CardContent>
                </Card>
              </>
            )}
          </QueryState>
          <Card>
            <CardHeader title="Connections" description={`${company.name}'s own links; other companies have their own.`} />
            <QueryState query={conns}>
              {(c) => (
                <CardContent className="space-y-3">
                  {c.items.map((x) => (
                    <ConnectionRow key={x.key} c={x} />
                  ))}
                </CardContent>
              )}
            </QueryState>
          </Card>
        </div>
      </div>

      <InviteDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        companyName={company.name}
        onInvited={(u) => setUsers((list) => [...(list ?? []), u])}
      />
    </div>
  )
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border pb-1.5 last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right font-medium">{v}</span>
    </div>
  )
}

function ConnectionRow({ c }: { c: Connection }) {
  const Icon = CONN_ICON[c.key] ?? Plug
  return (
    <div className="flex items-start gap-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">{c.label}</span>
          <StatusChip tone={CONN_TONE[c.status]}>{CONN_LABEL[c.status]}</StatusChip>
        </div>
        <div className="text-xs text-muted-foreground">
          {c.detail}
          {c.last_sync_at ? ` · last ${formatRelative(c.last_sync_at)}` : ''}
        </div>
      </div>
    </div>
  )
}

function InviteDialog({
  open,
  onOpenChange,
  companyName,
  onInvited,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  companyName: string
  onInvited: (u: CompanyUser) => void
}) {
  const [f, setF] = useState<UserInvite>({ name: '', login: '', role: 'store' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<Record<string, string>>({})

  async function submit(e: FormEvent) {
    e.preventDefault()
    const errors: Record<string, string> = {}
    if (!f.name.trim()) errors.name = 'Enter the name.'
    if (!f.login.trim()) errors.login = 'Mobile number or e-mail.'
    setErr(errors)
    if (Object.keys(errors).length) return
    setBusy(true)
    try {
      const res = await api.post<CompanyUser>('/api/company/users', f)
      // Mock mode answers with the contract sample; keep what the admin typed.
      onInvited({
        ...res,
        id: res?.id ?? `U-new-${Date.now()}`,
        name: f.name.trim(),
        login: f.login.trim(),
        role: f.role,
        status: 'invited',
        device: null,
        last_active_at: null,
        sign_in: f.login.includes('@') ? 'otp_email' : 'otp_phone',
      })
      toast.success(`${f.name.trim()} invited to ${companyName}. They sign in with an OTP.`)
      setF({ name: '', login: '', role: 'store' })
      onOpenChange(false)
    } catch (ex) {
      toast.error((ex as Error).message || 'Could not invite the user')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Invite a user</DialogTitle>
          <DialogDescription>They join {companyName} only and sign in with an OTP.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field label="Name" htmlFor="inv-name" error={err.name}>
            <Input id="inv-name" value={f.name} onChange={(e) => setF((p) => ({ ...p, name: e.target.value }))} />
          </Field>
          <Field label="Mobile number or e-mail" htmlFor="inv-login" error={err.login}>
            <Input id="inv-login" value={f.login} onChange={(e) => setF((p) => ({ ...p, login: e.target.value }))} />
          </Field>
          <Field label="Role" htmlFor="inv-role">
            <Select
              id="inv-role"
              value={f.role}
              options={ROLE_OPTIONS.filter((o) => o.value !== 'owner')}
              onValueChange={(v) => setF((p) => ({ ...p, role: v as Role }))}
            />
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              <Users /> Send invite
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
