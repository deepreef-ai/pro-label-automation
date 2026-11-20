import { lazy, Suspense, useEffect } from 'react'
import { createBrowserRouter, Outlet, useLocation, type RouteObject } from 'react-router-dom'
import { AppLayout } from './AppLayout'
import { RouteError } from './ErrorBoundary'
import { titleForPath } from './nav'

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

/** Root: keeps document.title in sync with the current screen. */
function Root() {
  const { pathname } = useLocation()
  useEffect(() => {
    const jc = /^\/jobs\/([^/]+)/.exec(pathname)?.[1]
    const title = jc ? `${decodeURIComponent(jc)} · Job 360` : titleForPath(pathname)
    document.title = `${title} · Pro Labels`
  }, [pathname])
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
          { path: '*', element: <NotFound /> },
        ],
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
