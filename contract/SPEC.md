# Shared Build Spec (source of truth for every contributor)

This file fixes the decisions everyone builds against. `contract/openapi.yaml`,
`contract/schema.md` and `contract/fixtures/` expand it. Change it only through a
separate `[contract]` PR approved by both developers.

## 1. Repo and runtime conventions

| Item | Decision |
|---|---|
| Python | 3.10+ (CI uses 3.11). Package root is `apps/api`; packages are `core`, `app`, `agents`, `chat`. Run with `PYTHONPATH=apps/api`. |
| API app | FastAPI instance `app` in `apps/api/app/main.py`. All routes start with `/api`. |
| DB | SQLite file `data/demo.db` (git-ignored) via SQLAlchemy 2.x. URL from env `DATABASE_URL`, default `sqlite:///data/demo.db`. Postgres-ready (no SQLite-only SQL). |
| Roles (demo) | Header `X-Role`: `owner`, `ppic`, `design`, `store`, `production`, `qc`, `dispatch`, `accounts`, `marketing` (plus `platform_admin` from v0.2). Missing header = `owner`. A forbidden call returns **403** `{"detail":"forbidden for role <r>"}`. From v0.2 the role and the company come from the login token; `X-Role` is kept for mock mode and `AUTH_MODE=demo` (section 6). |
| Owner-only | `PUT /api/settings`, `POST /api/clients/{id}/release-lock`. |
| Money | Rupees as numbers with 2 decimals; never strings. Dates are ISO `YYYY-MM-DD`; datetimes ISO 8601. |
| IDs | Job card `JC-####`, enquiry `ENQ-####`, quote `Q-####`, GRN `GRN-#####`, issue `ISS-#####`, roll `R-YYYY-####`, run `RUN-#####`, QC `QC-#####`, challan `DC-####`, invoice `INV-####`, plate `PL-#####`, die `D-###`. IDs are permanent (never row-based). |
| Demo data | Every generated row has `is_demo: true`; real rows from client files have `is_demo: false`. The UI shows a DEMO badge. |
| Errors | `{"detail": "<message>"}` with 400 (validation/rule broken), 401 (not signed in, v0.2 token mode), 403 (role), 404 (not found, also for another company's row), 409 (guard: e.g. dispatch above QC approved). |
| LLM | Never computes money/stock. All model calls go through `core.llm.gateway`. No network calls in tests. |

## 2. Business rules (from the client's Excel v12 system)

- Required metres = `order_qty / ups * repeat_mm / 1000`; ups = ups_across * ups_along. Planning adds **+10%**.
- Stock = opening (as of `stock_from`) + received - issued. UOM: metres to sq m = metres * width_mm / 1000.
- Wastage m = used - required; wastage % = wastage / required. Flag if wastage % > `wastage_tol` (default 0.15). Exactly equal passes.
- Over-production flag if printed > order_qty * (1 + `overprod_tol`) (default 0.10). Material flag if issued differs from **planned** metres (required + planning extra) by > `material_tol` (0.03); callers pass planned metres to `core.rules.production.material_flag`. Ink pool flag if actual vs estimate differs by > `ink_tol` (0.20). Slitting trim flag if > `slit_tol` (0.05). GRN rate flag if differs from item rate by > `grn_rate_tol` (0.05).
- "Printed" totals count **press** runs only (machines of type `press`), never offline machines.
- QC: approved + rejected must equal checked; checked must be <= printed. Rows with decision `Hold`, `Rework` or `Rejected` do not count as approved.
- Dispatch: cumulative dispatched for a job must be <= QC approved (else 409).
- Store issue **must** have a valid job card (else 400).
- ERP dates arrive as `dd-mm-yy` or `dd-mm-yyyy` text, or as dates Excel mis-read month-first. Always parse **day first**.
- Machine hour rate = (crew salary + other monthly cost) / hours run (per machine, per month). Crew cost = hours * rate. OEE = availability * performance * quality.
- Ink without a job card is pooled per month and shared to jobs in proportion to their estimated ink.
- Invoice: taxable = qty * rate; GST at `gst_rate` (default 0.18); due date = invoice date + client credit days (default 30).
- Lock: a client is LOCKED when any invoice is unpaid on a day **after** due date + `grace_days` (default 15). Day due+15 = not locked; due+16 = locked. Only the owner can release (logged with time).
- Ageing buckets by days past due: `not_due`, `1_30`, `31_60`, `61_90`, `90_plus`.
- Supplier bill due = bill date + min(vendor credit days, 45) if vendor is MSME, else bill date + credit days. Payments clear the **oldest bill first** (FIFO).
- Job profit = revenue - material - plates - ink - salaries - freight - admin_share - direct_overhead. Revenue = invoiced taxable, else PO value.
- Settings defaults: `wastage_tol 0.15, overprod_tol 0.10, material_tol 0.03, ink_tol 0.20, slit_tol 0.05, grn_rate_tol 0.05, grace_days 15, msme_days 45, gst_rate 0.18, planning_extra 0.10, admin_pct 0.05, ai_mode "cloud"`.

## 3. Screens and endpoints

| Screen | Endpoints |
|---|---|
| Shell | `GET /api/health`, `GET /api/search?q=`, `GET /api/settings`, `PUT /api/settings` (owner), `POST /api/feedback`, `GET /api/feedback` |
| Owner Dashboard | `GET /api/dashboard/summary?period=today\|month\|year`, `GET /api/alerts`, `GET /api/agents/brief` |
| Masters | `GET /api/clients`, `GET /api/clients/{id}`, `GET /api/vendors`, `GET /api/items`, `GET /api/machines` |
| Marketing | `GET /api/enquiries`, `POST /api/enquiries`, `POST /api/enquiries/{id}/quote`, `POST /api/enquiries/{id}/status`, `GET /api/marketing/summary` |
| Jobs (PPIC) | `GET /api/jobs?status=&q=`, `GET /api/jobs/{job_card}`, `POST /api/jobs`, `POST /api/jobs/from-po` (multipart PDF -> draft, not saved), `GET /api/planning/material-summary` |
| Design | `GET /api/design?stage=`, `GET /api/design/{job_card}`, `PUT /api/design/{job_card}`, `GET /api/plates`, `GET /api/dies` |
| Job 360 | `GET /api/jobs/{job_card}/360` |
| Store | `GET /api/store/summary`, `GET /api/store/stock`, `GET /api/store/grns`, `POST /api/store/grns`, `GET /api/store/issues`, `POST /api/store/issues`, `GET /api/store/rolls`, `GET /api/store/slitting`, `GET /api/store/party-laminate`, `GET /api/store/ink-allocation`, `GET /api/store/data-quality` |
| Production | `GET /api/production/runs`, `POST /api/production/runs/start`, `POST /api/production/runs/{id}/end`, `GET /api/production/press-setup/{job_card}`, `POST /api/production/press-setup`, `GET /api/production/oee`, `GET /api/production/morning-report`, `GET /api/production/counter/stream?run_id=` (SSE) |
| QC | `GET /api/qc`, `POST /api/qc` |
| Dispatch | `GET /api/dispatch`, `POST /api/dispatch`, `GET /api/dispatch/{id}/challan.pdf` |
| Money | `GET /api/invoices`, `POST /api/invoices/draft-from-dispatch/{dispatch_id}`, `POST /api/invoices/{id}/issue` (draft -> open, v0.2), `GET /api/debtors`, `POST /api/clients/{id}/release-lock` (owner), `GET /api/collections`, `POST /api/collections`, `GET /api/creditors`, `POST /api/payments`, `GET /api/cashplan`, `GET /api/pnl?month=YYYY-MM` |
| Agents Center | `GET /api/agents`, `GET /api/agents/findings?status=open\|done\|rejected`, `POST /api/agents/run` (body `{"agent": "<name>"\|"all"}`), `POST /api/agents/findings/{id}/approve`, `POST /api/agents/findings/{id}/reject` (body `{"reason"}`), `POST /api/agents/findings/{id}/edit` (body `{"payload"}`), `GET /api/outbox` |
| Floor Board | `GET /api/floor/board` |
| Auth (v0.2) | `POST /api/auth/otp`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` |
| Platform admin (v0.2, screens 17, 18, 20) | `GET /api/platform/companies`, `POST /api/platform/companies`, `POST /api/platform/companies/{id}/import` (multipart template), `GET /api/platform/usage?month=YYYY-MM` |
| Company admin (v0.2, screen 19) | `GET /api/company/profile`, `GET /api/company/users`, `POST /api/company/users`, `PUT /api/company/users/{id}`, `GET /api/company/connections` |
| Chat | `POST /api/chat` (body `{"message", "history"?, "role"?}` -> `{"reply", "actions":[{"type":"navigate","to"}\|{"type":"draft",...}], "sources":[...]}`), `GET /api/chat/suggestions` |

## 4. Agents (names are fixed)

`import_checker`, `store_watchdog`, `wastage_watchdog`, `planning`, `collections`, `payables`, `month_end`, `owner_brief`.
A finding: `{id, agent, created_at, severity: high|medium|low, title, detail, evidence: [{label, link}], suggested_action: {type, payload}, status: open|done|rejected, decided_by, decided_at, reason}`.

## 4b. Chat safety interface (implemented in `apps/api/chat/`, checked by locked test 6)

- `chat.tools.TOOLS: dict[str, Tool]`. `Tool` has `name`, `description`, `mode` (`"read"` or `"draft"`), `run(args: dict, ctx: ToolContext) -> dict`.
- `ToolContext` has `role: str` and `api` (an object with `get(path) -> dict` and `post(path, body) -> dict`, which call the public HTTP API with `X-Role`). Tools never import DB models, and **no tool ever calls `api.post`/`put`**: `read` tools may call `api.get`; `draft` tools only return `{"type": "draft", "endpoint": "...", "body": {...}, "summary": "..."}` for the user to confirm in the UI.
- `chat.service.answer(message: str, *, role: str = "owner", history: list | None = None, gateway=None, api=None) -> ChatReply` with fields `reply: str`, `actions: list[dict]`, `sources: list[dict]`. Actions are `{"type": "navigate", "to": "/jobs/JC-1301"}` or a draft dict as above.
- If the gateway raises `LLMUnavailable`, `answer` still works through a deterministic intent router for at least: "open <job card>" -> navigate, "show debtors" -> navigate to `/money`, "go to <screen>" -> navigate.
- Before any cloud call, client/vendor names are anonymised by `core.llm` (cloud mode only).

## 5. Frontend conventions

- `apps/web`: React 18 + Vite + TypeScript + Tailwind CSS v4 + Radix primitives (shadcn-style components in `src/components/ui`), Recharts, lucide-react, framer-motion, react-router.
- One API client `src/lib/api.ts`. `VITE_API_MODE=mock` (default until W6) resolves calls from `contract/fixtures/index.json`; `live` calls the backend at `VITE_API_URL` (default `http://localhost:8000`). The role switcher sends `X-Role`.
- Routes: `/` dashboard, `/marketing`, `/jobs`, `/jobs/:jobCard`, `/design`, `/store`, `/production`, `/qc`, `/dispatch`, `/money`, `/agents`, `/floor` (full screen), `/settings`.
- Page folders: `src/pages/<area>/` (one owner per folder). Shared UI in `src/components/`. The router registers every page from W1 onward (placeholders until filled).
- Design rules: one button style, one card style, one radius scale; equal content edges; hover lift 2px on clickable cards, buttons press on click; no fade-in on scroll, no tilt, no carousels; no violet/lavender; visible focus rings; 44px touch targets on tablet screens; text contrast WCAG AA; INR formatting with lakh/crore (`en-IN`).

## 6. Multi-tenant (v0.2)

One app serves many label companies. Each company sees **only its own data**, has its own users, settings and AI budget, and pays its share of a small shared cost. Pro Labels is company `CO-001`; the demo adds two **made-up** companies (`CO-002` Sunrise Flexo Prints, `CO-003` Nilgiri Label Works) with synthetic data only.

**6.1 Data**

| Rule | Decision |
|---|---|
| Company | Table `companies` (`id` `CO-###`, `name`, `slug` unique, `status` `onboarding`/`parallel_run`/`live`/`paused`, `ai_budget_month`, ...). |
| Every row | Every business table has `company_id` (not null, indexed, FK `companies`). Business ids stay as they are (`JC-1301`) but are unique **per company**: keys become `(company_id, id)`. Two companies may both have `JC-1301`. |
| Isolation | One helper adds `company_id = :current` to every read and write (SQLite demo). The PostgreSQL option also turns on **row-level security** policies on every table, so a missing filter still returns nothing. |
| Shared tables | Only platform tables have no `company_id`: `companies`, `users` (has `company_id`, null for platform staff), `ai_usage` and `imports` (both carry `company_id`). |
| Settings | `settings` has one row **per company** (same fields and defaults as section 2). `PUT /api/settings` changes the signed-in company only. |
| Rules | `core.rules` does not change: it is pure maths with no company. |

**6.2 Who is calling**

- The **current company comes only from the login token**, never from the URL, query or body. Request bodies have no `company_id` field; one sent anyway is ignored.
- Login (demo): `POST /api/auth/otp` `{company_slug, login}`, then `POST /api/auth/login` `{company_slug, login, otp}` returns `{token, token_type: "Bearer", expires_at, user, company}`. Send `Authorization: Bearer <token>` on every call. The token is signed; its claims are `company_id`, `user_id`, `role`, `exp`. In `AUTH_MODE=demo` the OTP is always `123456` and `POST /api/auth/otp` returns it in `demo_otp` (null in token mode).
- `AUTH_MODE` (env): `demo` (default on the demo laptop and in tests) = a call **without** a token acts as the `CO-001` owner and `X-Role` still works, so v0.1 screens, mock mode and the locked tests keep working. `token` = every call except `POST /api/auth/otp` and `POST /api/auth/login` needs a valid token. A sent token always wins over `X-Role`.
- 401 `{"detail": "not signed in"}`: token missing (token mode), expired, tampered, or naming an unknown or paused company / disabled user.
- Roles: the nine company roles keep their meaning **inside** the company. The company `owner` is also its **company admin** (users, profile, connections, settings). `platform_admin` is platform staff: no company, allowed only on `/api/platform/*` and `/api/auth/*`; every company endpoint returns 403 `forbidden for role platform_admin`, so platform staff never see a company's jobs, stock or money.
- Another company's row is **404**, never 403 (do not confirm it exists). Lists and searches return only the current company's rows.
- The audit log stores `company_id` and `user_id` with every write.

**6.3 Platform admin (screens 17, 18, 20)**

- Companies list: status, active users, isolation (always on), last import, AI budget used, cost this month.
- Add company: create the company and its first admin (role `owner`, status `invited`); then upload the **standard onboarding template** (`.xlsx`, one sheet each: `clients`, `vendors`, `items`, `machines`, `opening_stock`, `unpaid_invoices`). Every sheet is checked (required columns, units, widths, GSTIN, item names, day-first dates). Good rows are saved with the new `company_id`; bad rows are **held back** and listed in `fixes` (sheet, row, column, value, problem, fix) for the company to correct and re-upload. Nothing is ever copied from another company.
- Cost & usage: shared cost lines (server, database, storage, domain) are split across companies **by active users**; per-use costs (AI calls, OTP messages) are charged to the company that used them. `growth` shows the estimated cost per company as more companies join.

**6.4 AI budget (Udit: minimum cost)**

- Each company has `ai_budget_month` (rupees). `core.llm` counts AI spend per company per month. At **80%** (`ai_alert_pct`) the owner and platform admin are warned; at 100% (`ai_over_budget`) every AI feature (chat, agent wording, PO reader) uses its deterministic fallback until the next month. The demo never breaks.
- The answer cache is per company (never shared). Name masking before cloud calls is unchanged.
- Chat, agents, findings, outbox and documents (RAG) are per company: tools call the API with the user's token, and an id from another company counts as ungrounded.

**6.5 Rollout of the contract**

New operations carry `x-status: planned` (and `x-since: v0.2`) in `openapi.yaml` until the backend task that builds them is merged. For the same reason `platform_admin` is added to the `X-Role` enum (and so to every operation's role tests) only in the `[contract]` PR after B1, once every route, including chat, rejects it on company endpoints. The locked contract test (`test_api_contract.py`) skips planned operations; right after B1 (auth) and B2 (platform/company) merge, a small `[contract]` PR removes the marker so the operations are fully tested from then on. Mock mode serves planned operations from their fixtures like any other.
