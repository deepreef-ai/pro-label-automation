# Pro Labels · AI Ops — web app

React 18 + Vite + TypeScript (strict) + Tailwind CSS v4 + Radix primitives. Every screen of the demo lives here.

## Run it

```bash
cd apps/web
npm install          # once
npm run dev          # http://localhost:5173 (mock data, no backend needed)
```

| Script | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check (`tsc -b`) and build to `dist/` |
| `npm run preview` | Serve the built app (`--port 4173` for the smoke test) |
| `npm run typecheck` | Type-check only |
| `npm run lint` | ESLint (typescript-eslint + react-hooks) |
| `npm run test:e2e` | Playwright smoke test in `e2e/` (builds and previews automatically). Set `PW_CHANNEL=chrome` to use the installed Chrome instead of Playwright's Chromium. |

## Mock vs live data

Copy `.env.example` to `.env.local` to change these:

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_MODE` | `mock` | `mock` answers every call from `contract/fixtures/`. `live` calls the FastAPI backend. |
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL in live mode. |

**Mock mode** reads `contract/fixtures/index.json`, which maps a request key to a fixture file, e.g.
`{"GET /api/jobs/{job_card}": "job_detail.json", "GET /api/dashboard/summary?period=month": "dashboard_month.json"}`.
Matching rules: method + path, `{param}` segments match anything, literal segments beat params, an exact query
variant beats the plain key, and the plain key is the fallback for any query. Calls take 150–300 ms to feel real.
A GET with no fixture returns "No data yet" (`noData: true`), never a crash. A POST/PUT with no fixture returns
`{ ok: true, ...body }`.

**Live mode** sends `fetch(VITE_API_URL + path)` with the `X-Role` header from the role switcher. Errors surface the
backend's `{"detail"}` message.

## Using the API

```tsx
import { api, useApi, withQuery } from '@/lib/api'
import { QueryState, DataTable } from '@/components/ui'

const q = useApi<Job[]>(withQuery('/api/jobs', { status }))   // { data, loading, error, noData, refetch }
return <QueryState query={q}>{(jobs) => <DataTable rows={jobs} columns={cols} />}</QueryState>

await api.post('/api/qc', body)    // mutations
```

Types for API payloads come from `@contract/types` (`contract/types.ts`).

## Folder ownership

Each page owner edits **only their folder**. The router (`src/app/routes.tsx`) already registers every route and
lazily loads `src/pages/<area>/index.tsx` (default export).

| Route | File | Owner task |
|---|---|---|
| `/` | `src/pages/dashboard/index.tsx` | W2 |
| `/marketing` | `src/pages/marketing/index.tsx` | page owner |
| `/jobs` | `src/pages/jobs/index.tsx` | page owner |
| `/jobs/:jobCard` | `src/pages/jobs/job360.tsx` | page owner |
| `/design` | `src/pages/design/index.tsx` | page owner |
| `/store` | `src/pages/store/index.tsx` | page owner |
| `/production` | `src/pages/production/index.tsx` | page owner |
| `/qc` | `src/pages/qc/index.tsx` | page owner |
| `/dispatch` | `src/pages/dispatch/index.tsx` | page owner |
| `/money` | `src/pages/money/index.tsx` | page owner |
| `/agents` | `src/pages/agents/index.tsx` | page owner |
| `/floor` | `src/pages/floor/index.tsx` (full screen, no shell) | page owner |
| `/settings` | `src/pages/settings/index.tsx` | page owner |
| chat panel | `src/chat/` (`ChatLauncher` export is mounted by the shell) | C1 |
| shell + design system | `src/app/`, `src/components/ui/`, `src/lib/`, `src/styles/` | W1 |

Put page-only components next to the page (`src/pages/<area>/…`). Anything two pages need goes in
`src/components/`.

## Page rules (keep every screen consistent)

- Start every page with `<PageHeader title="…" subtitle="…" actions={…} />`. It renders the page's single `<h1>`;
  the title must stay exactly as in the table above (the smoke test checks it).
- Use the shared components from `@/components/ui`: `Button` (primary / secondary / ghost / destructive;
  sizes sm / md / lg / `touch` for tablet screens), `Card` (`interactive` lifts 2px), `Badge`, `StatusChip` +
  `toneForStatus()`, `DemoBadge` for `is_demo` rows, `KpiCard` + `Sparkline`, `DataTable`, `Skeleton`,
  `EmptyState`, `QueryState`, `Tabs` / `Segmented`, `Dialog`, `Sheet`, `Tooltip`, `Select`, `Switch`, `Input` /
  `Textarea` / `Field`, `DropdownMenu`, `Popover`, `toast`, `ApprovalCard`, `Timeline`, `ProgressSteps`.
- Format with `@/lib/format`: `formatINRShort` (₹4.2 L, ₹2.32 Cr), `formatINR` (₹35,400.00), `formatNumber`,
  `formatCompact`, `formatPercent(0.153)` → 15.3%, `formatDate` → 21 Nov 2026.
- Colours come only from tokens (`bg-surface`, `text-muted-foreground`, `border-border`, `bg-accent`,
  `text-ok-foreground`, `bg-warn-soft`, `text-danger-foreground`, `chart-1..5` …), defined in
  `src/styles/tokens.css` for light and dark. No raw hex colours in pages.
- Radius: `rounded-sm / md / lg / xl` only. No fade-in on scroll, no tilt, no carousels.
- Current role: `useRole()` from `@/lib/role`. Theme: `useTheme()` from `@/app/theme`.
