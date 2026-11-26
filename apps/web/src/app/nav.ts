import {
  Bot,
  ClipboardCheck,
  Factory,
  IndianRupee,
  LayoutDashboard,
  Megaphone,
  MonitorPlay,
  Package,
  Palette,
  Settings,
  Truck,
  BriefcaseBusiness,
  Building2,
  ChartPie,
  CirclePlus,
  type LucideIcon,
} from 'lucide-react'
import type { Role } from '@/lib/role'

export interface NavItem {
  /** Route path */
  to: string
  /** Page title: also the <h1> and document title */
  title: string
  icon: LucideIcon
  /** Roles that see this item in the sidebar. Owner sees everything. */
  roles: Role[] | 'all'
  /** Short description for the command palette */
  description: string
  keywords?: string
}

export interface NavGroup {
  label: string | null
  items: NavItem[]
}

/**
 * Sidebar structure. Role visibility follows the demo role list (SPEC §1):
 * each department sees its own screens plus Jobs, Agents Center and Settings.
 */
export const NAV: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      {
        to: '/',
        title: 'Dashboard',
        icon: LayoutDashboard,
        roles: ['owner', 'ppic', 'accounts'],
        description: 'Today, month and year at a glance',
        keywords: 'home kpi profit cash brief',
      },
      {
        to: '/agents',
        title: 'Agents Center',
        icon: Bot,
        roles: 'all',
        description: 'AI findings waiting for approval',
        keywords: 'ai findings approve reject outbox',
      },
    ],
  },
  {
    label: 'Sales & Planning',
    items: [
      {
        to: '/marketing',
        title: 'Marketing',
        icon: Megaphone,
        roles: ['owner', 'ppic', 'marketing', 'accounts'],
        description: 'Enquiries, quotes and targets',
        keywords: 'enquiry quote won lost target sales',
      },
      {
        to: '/jobs',
        title: 'Jobs',
        icon: BriefcaseBusiness,
        roles: 'all',
        description: 'Job register, paper needs and new job from PO',
        keywords: 'ppic job card po planning paper shortage',
      },
      {
        to: '/design',
        title: 'Design',
        icon: Palette,
        roles: ['owner', 'ppic', 'design', 'production', 'marketing'],
        description: 'Artwork, proofs, plates and dies',
        keywords: 'artwork proof approval plates dies press setup',
      },
    ],
  },
  {
    label: 'Shop floor',
    items: [
      {
        to: '/store',
        title: 'Store',
        icon: Package,
        roles: ['owner', 'ppic', 'store', 'production', 'accounts'],
        description: 'Stock, receipts, issues, rolls and ink',
        keywords: 'grn issue stock rolls slitting ink inventory',
      },
      {
        to: '/production',
        title: 'Production',
        icon: Factory,
        roles: ['owner', 'ppic', 'production', 'qc'],
        description: 'Press runs, counters, wastage and OEE',
        keywords: 'press run counter wastage oee machine',
      },
      {
        to: '/qc',
        title: 'QC',
        icon: ClipboardCheck,
        roles: ['owner', 'ppic', 'production', 'qc', 'dispatch'],
        description: 'Checked, approved and rejected labels',
        keywords: 'quality check approve reject defect',
      },
      {
        to: '/dispatch',
        title: 'Dispatch',
        icon: Truck,
        roles: ['owner', 'ppic', 'qc', 'dispatch', 'accounts'],
        description: 'Delivery challans and shipments',
        keywords: 'challan delivery shipment',
      },
    ],
  },
  {
    label: 'Finance',
    items: [
      {
        to: '/money',
        title: 'Money',
        icon: IndianRupee,
        roles: ['owner', 'accounts'],
        description: 'Invoices, debtors, creditors, cash plan, P&L',
        keywords: 'invoice debtors creditors collections payments cash pnl profit gst msme lock',
      },
    ],
  },
  {
    label: 'Display',
    items: [
      {
        to: '/floor',
        title: 'Floor Board',
        icon: MonitorPlay,
        roles: ['owner', 'ppic', 'production', 'qc', 'store', 'dispatch'],
        description: 'Full-screen TV view per press',
        keywords: 'tv display board press',
      },
    ],
  },
  {
    label: null,
    items: [
      {
        to: '/settings',
        title: 'Settings',
        icon: Settings,
        roles: 'all',
        description: 'Tolerances, AI mode and preferences',
        keywords: 'tolerance settings ai mode gst',
      },
    ],
  },
]

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items)

/**
 * Platform admin (demo v0.2, screens 17, 18, 20). Seen by `platform_admin` only, plus the demo presenter
 * (owner, not signed in). Platform staff never see a company's screens (contract §6.2).
 */
export const PLATFORM_NAV: NavGroup = {
  label: 'Platform',
  items: [
    { to: '/platform', title: 'Companies', icon: Building2, roles: ['owner'], description: 'All customer companies on the platform', keywords: 'tenants companies platform admin' },
    { to: '/platform/add-company', title: 'Add company', icon: CirclePlus, roles: ['owner'], description: 'Onboard a new company in six steps', keywords: 'onboarding new tenant import template' },
    { to: '/platform/usage', title: 'Cost & usage', icon: ChartPie, roles: ['owner'], description: 'Shared cost and cost per company', keywords: 'cost billing usage ai budget' },
  ],
}

export function canSee(item: NavItem, role: Role): boolean {
  return role === 'owner' || item.roles === 'all' || item.roles.includes(role)
}

export function navForRole(role: Role): NavGroup[] {
  return NAV.map((g) => ({ ...g, items: g.items.filter((i) => canSee(i, role)) })).filter((g) => g.items.length > 0)
}

/** Page title for a pathname (used for document.title and the feedback dialog). */
export function titleForPath(pathname: string): string {
  if (/^\/jobs\/[^/]+/.test(pathname)) return 'Job 360'
  const platform = PLATFORM_NAV.items.find((i) => i.to === pathname)
  if (platform) return platform.title
  const hit = NAV_ITEMS.find((i) => i.to === pathname || (i.to !== '/' && pathname.startsWith(i.to + '/')))
  return hit?.title ?? (pathname === '/' ? 'Dashboard' : 'Not found')
}
