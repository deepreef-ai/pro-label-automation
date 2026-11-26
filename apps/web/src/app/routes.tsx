import { lazy, Suspense, useEffect } from 'react'
import { createBrowserRouter, Outlet, useLocation, type RouteObject } from 'react-router-dom'
import { AppLayout } from './AppLayout'
import { RouteError } from './ErrorBoundary'
import { titleForPath } from './nav'
import { currentCompany, useSession } from '@/lib/session'

/*
 * Every route from SPEC §5. Each page lives in src/pages/<area>/ and is loaded lazily,
 * so contributors only ever touch their own folder.
 */
const DashboardPage = lazy(() => import('@/pages/dashboard/index'))
const MarketingPage = lazy(() => import('@/pages/marketing/index'))
const JobsPage = lazy(() => import('@/pages/jobs/index'))
const Job360Page = lazy(() => import('@/pages/jobs/job360'))
const DesignPage = lazy(() => import('@/pages/design/index'))
const StorePage = lazy(() => import('@/pages/store/index'))
const ProductionPage = lazy(() => import('@/pages/production/index'))
const QcPage = lazy(() => import('@/pages/qc/index'))
const DispatchPage = lazy(() => import('@/pages/dispatch/index'))
const MoneyPage = lazy(() => import('@/pages/money/index'))
const AgentsPage = lazy(() => import('@/pages/agents/index'))
const FloorBoardPage = lazy(() => import('@/pages/floor/index'))
const SettingsPage = lazy(() => import('@/pages/settings/index'))
const NotFound = lazy(() => import('./NotFound'))
const LoginPage = lazy(() => import('@/pages/login/index'))
const PlatformCompaniesPage = lazy(() => import('@/pages/platform/index'))
const PlatformAddCompanyPage = lazy(() => import('@/pages/platform/add-company'))
const PlatformUsagePage = lazy(() => import('@/pages/platform/usage'))

/** Root: keeps document.title in sync with the current screen. */
function Root() {
  const { pathname } = useLocation()
  const session = useSession()
  useEffect(() => {
    if (pathname === '/login') {
      document.title = 'Sign in · Label AI Ops'
      return
    }
    const jc = /^\/jobs\/([^/]+)/.exec(pathname)?.[1]
    const title = jc ? `${decodeURIComponent(jc)} · Job 360` : titleForPath(pathname)
    document.title = `${title} · ${currentCompany().name}`
  }, [pathname, session])
  return <Outlet />
}

function FullScreenFallback() {
  return <div className="min-h-screen bg-background" aria-busy="true" />
}

export const routes: RouteObject[] = [
  {
    element: <Root />,
    errorElement: <RouteError />,
    children: [
      {
        element: <AppLayout />,
        errorElement: <RouteError />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'marketing', element: <MarketingPage /> },
          { path: 'jobs', element: <JobsPage /> },
          { path: 'jobs/:jobCard', element: <Job360Page /> },
          { path: 'design', element: <DesignPage /> },
          { path: 'store', element: <StorePage /> },
          { path: 'production', element: <ProductionPage /> },
          { path: 'qc', element: <QcPage /> },
          { path: 'dispatch', element: <DispatchPage /> },
          { path: 'money', element: <MoneyPage /> },
          { path: 'agents', element: <AgentsPage /> },
          { path: 'settings', element: <SettingsPage /> },
          // Platform admin (demo v0.2, screens 17, 18, 20)
          { path: 'platform', element: <PlatformCompaniesPage /> },
          { path: 'platform/add-company', element: <PlatformAddCompanyPage /> },
          { path: 'platform/usage', element: <PlatformUsagePage /> },
          { path: '*', element: <NotFound /> },
        ],
      },
      {
        // Screen 16: company sign-in, full screen (demo v0.2, W1)
        path: 'login',
        element: (
          <Suspense fallback={<FullScreenFallback />}>
            <LoginPage />
          </Suspense>
        ),
      },
      {
        // Floor Board: full screen, no sidebar / top bar
        path: 'floor',
        element: (
          <Suspense fallback={<FullScreenFallback />}>
            <FloorBoardPage />
          </Suspense>
        ),
      },
    ],
  },
]

export const router = createBrowserRouter(routes, {
  future: {
    v7_relativeSplatPath: true,
    v7_fetcherPersist: true,
    v7_normalizeFormMethod: true,
    v7_partialHydration: true,
    v7_skipActionErrorRevalidation: true,
  },
})
