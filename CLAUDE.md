# CLAUDE.md: rules for every Claude session working in this repo

Two developers (Vinay and Yash) each work with their own Claude. Both Claudes follow this file.

## What this project is
A demo of an AI-powered operations system for a label-printing plant: one web app (13 screens), a chatbot and 8 AI agents, replacing 11 linked Excel workbooks. Read `contract/SPEC.md` first: it holds the business rules, the endpoint list and the conventions. `contract/openapi.yaml`, `contract/schema.md` and `contract/fixtures/` expand it. The client walkthrough is `docs/DEMO_SCRIPT.md`.

## Current status (update this when it changes)
- **Team change (2026-11-24):** Yash replaced Ravi and owns backend, agents and infra. Senior reviewer: Udit.
- **Now building demo v0.2: multi-tenant from day 1** (Udit). One app, many label companies; every row carries a `company_id`; the company comes **only from the login token**; each company has its own users, settings and AI budget; extra demo companies use **synthetic** data (never copies of client data). Plan: milestone *Demo v0.2 (multi-tenant)*, pinned Task Board #64, tasks #47-#63 in this order: H1 -> H2 -> K1 `[contract]` -> K2 `[tests]` -> F1 -> F2 -> B1 -> (B2, B3, C1) -> W1-W3 (mock mode from K1) -> W4 -> G1 -> D1 -> R1.
- **v0.2 progress (2026-11-26):** merged H2 (#65, #66), K1 (#67), K2 (#69), F1 (#71), F2 (#72), W1 (#68), W2 (#70), W3 (#73). Open: B1 #53, B2 #54, B3 #55, C1 #59, W4 #60, G1 #61, D1 #62 (demo script v0.2 in `docs/DEMO_SCRIPT.md`), R1 #63.
- **Demo v0.1 is feature-complete on `dev`** (2026-11-20): Task 0 (#1-#7), web W1-W6 (#8-#14), chatbot C1 (#13), API A1-A3 (#15-#17), agents G1 (#18), run scripts G2 (#19). All issues closed; Task Board is #20.
- `dev` CI is fully green; all 4 checks (`integrity`, `backend`, `integration`, `web`) are **required** on `dev` and `main`. Integration: 143/143.
- Every screen runs **live** against the API with no "Sample data" badge; mock mode still works (`npm run dev`).
- **Next:** manual test + two rehearsals with `docs/DEMO_SCRIPT.md`, backup video, then a `[release]` PR `dev` -> `main` and tag `v0.1-demo`.
- **After the demo** (follow-ups, not blockers):
  - JC-1301 profit: fixtures say Rs 9,425; the live API computes Rs 9,375 (admin/overhead split). Align them.
  - `/api/dashboard/summary` and `/api/floor/board` return fields not in `openapi.yaml` (`top_jobs`, `bottom_jobs`, `trend_30d`, `machines`, `oee`, `queue`, ...): document them in a `[contract]` PR.
  - Real job cards are 8 digits (`JC-22244284`), not `JC-####` as SPEC says; the UI and chat accept both.
  - `core.rules.money.client_locked` treats an invoice with no balance as paid; tighten it with a `[tests]` + rules PR.
  - `store_watchdog` emits ~140 findings per run; consider grouping.

## Who owns what (edit only your owner's folders)
| Folder | Owner |
|---|---|
| `apps/web/`, `apps/api/chat/` | Vinay (frontend + chatbot) |
| `apps/api/app/`, `apps/api/agents/`, `infra/` | Yash (backend API + agents + infra) |
| `apps/api/core/` (rules engine, models, ETL, LLM gateway) | Shared foundation; change only with the other developer's review |
| `contract/`, `tests/`, `apps/web/e2e/`, `.github/`, `scripts/ci/`, `pyproject.toml` | LOCKED: only in a separate PR titled `[contract]`, `[tests]` or `[ci]`, approved by the other developer |

Before editing, ask your developer which task (GitHub issue) you are on, and stay inside that task's folders.

## Branch flow
```
main  <- stable, demo-ready; only "[release] ..." PRs from dev
 dev  <- integration branch; every feature PR targets dev
  feat/<task>  <- one branch per issue, created from the latest dev
```
1. `git checkout dev && git pull` then `git checkout -b feat/<task>` (branch names are in each issue).
2. Small commits; before opening a PR run `git pull --rebase origin dev` and the tests.
3. Open the PR **into `dev`** with `Closes #<n>`, a summary, the endpoints/screens touched and how to test.
4. CI must be green and the other developer approves; then squash-merge and delete the branch.
5. Merge reviewed PRs quickly; never let many PRs pile up (that is what causes conflicts).

**Lessons from v0.1 (avoid repeating them):**
- Always branch from the **latest `dev`** and open PRs **into `dev`** (one PR was opened against `main` by mistake).
- Don't stack PRs on another feature branch. If you must, delete the base branch right after it merges, or the stacked PRs merge into it instead of `dev` (happened with #23-#27; fixed by #30). "Automatically delete head branches" is on.
- "Branch must be up to date" is required and stale approvals are dismissed: **Update branch -> wait for CI -> approve -> merge immediately**, or the approval is lost again.
- Only reviewers with **Write** access count as approvals.
- `.gitignore` patterns must be anchored (`/models/`, not `models/`): the unanchored one hid `apps/api/core/models/` (#28).
- A PR touching locked paths must be titled `[tests]`, `[ci]` or `[contract]` and touch only locked paths, or `integrity` fails.

## Hard rules
- The repo is **PUBLIC**: never commit client files, `data/`, `.env`, keys, `*.db`, `*.xlsx`. Real client data lives only in the local, git-ignored `data/raw/`.
- Never edit, skip or weaken tests to make a PR pass (`skip`, `xfail`, `.only` and lowering coverage fail CI).
- All money, stock and tolerance maths goes through `core.rules` (never re-implement it, never let an LLM compute it).
- All LLM calls go through `core.llm.get_gateway()` (providers with fallback; anonymised in cloud mode). If the LLM is unavailable, fall back to deterministic text: the demo must never break.
- Never print, log or commit API keys. They live only in the local `.env` (git-ignored); `.env.example` lists names only. GitHub secret scanning and push protection are on.
- AI may only **draft**; anything that changes data needs a human confirm.
- Build endpoints and screens exactly to `contract/`. If the contract is wrong, open a `[contract]` PR first.

## Backend API conventions (`apps/api/app/`, set by A1 #15; follow them in A2/A3/G1)
- **Layout:** `app/main.py` registers one router per screen area (`app/routers/<area>.py`). Business logic lives in `app/services/<area>.py`. Reuse existing services and don't duplicate serializers: there is one `Job` shape, `services/jobs.list_jobs/get_job`; client lock status comes from `services/clients.client_lock/client_locks`; settings and tolerances from `routers/shell.load_settings`.
- **Roles:** every route has `dependencies=[allow(<x-roles from openapi.yaml>)]` (`app/deps.py`). A missing `X-Role` means owner; an unknown role gets 403 `{"detail": "forbidden for role <r>"}`. Route-level dependencies run before body validation, so a forbidden caller gets 403 even when the body is bad.
- **Signatures:** use the aliases `def route(db: DB, role: Role)`. Ruff B008 forbids `= Depends(...)` defaults.
- **DB access:** SQLAlchemy Core through `T("<table>")`, using the `core.models` table names. Never write `from core import models` in app code: the integration conftest re-imports `core.db` for each test database, and that form returns a stale module.
- **Writes:** every write calls `app.audit.audit(...)` before `db.commit()`. New ids come from `app.audit.next_id(db, table, prefix, width)`; they are permanent and never row-based.
- **Errors:** raise `bad_request` (400), `not_found` (404) or `conflict` (409) from `app.deps`. Validation errors already become 400 `{"detail": "..."}` in `main.py`.
- **Wire format:** `app.serialize.row_dict/jsonable/money` turn Decimals into numbers, dates into ISO, and naive timestamps into IST.
- **Demo date:** `app.deps.today()` is 2026-11-20 (the fixture story), overridable with `DEMO_TODAY`. Use it, not `date.today()`, for locks, ageing and "late" flags.
- **Lock rule:** when you call `core.rules.money.client_locked`, always pass an explicit balance per invoice. An invoice without one counts as paid (known rules bug, reported on PR #21).
- **Partial PRs:** the locked integration suite covers every endpoint, so a partial backend PR is green only for its own endpoints. List the expected failures (by owning issue) in the PR description.

## AI layer (`apps/api/core/llm/`, #43)
- Providers, each enabled only when its key is in `.env`: Claude (official `anthropic` SDK, `claude-opus-5-5`), Groq, Gemini, Cerebras, SambaNova, Mistral, NVIDIA, GitHub Models, OpenRouter, Hugging Face, Ollama (local).
- Up to 9 keys per provider (`GROQ_API_KEY`, `GROQ_API_KEY_2` ... `_9`), round-robin; a key that hits 429/quota/5xx/bad-key rests `LLM_COOLDOWN_SECONDS` (60).
- `LLM_ORDER` sets priority; `LLM_PARALLEL=2` races the first healthy providers (first good answer wins). Claude is paid and is billed even when it loses a race: put free providers first unless Claude is needed.
- Gemini model ids retire often; defaults are env-overridable (`GEMINI_MODEL=gemini-flash-latest`, etc.).
- On the demo laptop the working providers were Groq, Gemini and OpenRouter (2026-11-20); the others' keys were rejected by the providers.

## Chatbot rules (`apps/api/chat/`, #27, #44, #45)
- Navigation intents ("open JC-1301", "store kholo") are answered by a deterministic router, no LLM.
- **Factual questions** (locks, profit, flags, reminders, GRN, release) use the exact tool-backed template answer first (`deterministic_answer`); free models paraphrase IDs or invent rows.
- Any LLM answer containing an unrestored privacy alias (`Client-017`, "Client A") or a job card that does not exist is replaced by the tool answer (`_ungrounded`).
- The prompt always states the reply language (`(Answer in English.)` / `(Answer in Hindi.)`).
- Tools only read or **draft**; drafts are confirmed in the UI. Demo vendor for GRN drafts: `Polyfilm Industries` (synthetic; never use the client's real vendor names in committed files).

## Running things
**Whole app (Windows, PowerShell, from the repo root):**
```powershell
.\run-demo.cmd     # loads .env, installs on first run, builds data/demo.db (real data if data/raw exists, else synthetic), starts API :8000 + web :5173, opens the browser
.\stop-demo.cmd    # stop everything
.\reset-demo.cmd   # rebuild the demo DB (between rehearsals)
```
In PowerShell use `cd D:\path` (not `cd /d`) and prefix scripts with `.\`. A fresh clone without `data/raw` and without keys still runs (synthetic DB, chatbot fallbacks). Needs Git, Python 3.10+, Node 20+.

**Pieces separately:**
```bash
# Python (from repo root)
python -m venv .venv && .venv\Scripts\activate
pip install -r apps/api/requirements.txt -r requirements-dev.txt
set PYTHONPATH=apps/api
python -m core.etl.extract --raw data/raw --out data/extract   # needs the client files locally
pytest tests/unit -q                                            # rules engine (locked)
pytest tests/integration -q                                     # contract, demo flow, AI safety (locked)

python -m core.etl.build_demo_db --raw data/raw --db sqlite:///data/demo.db   # or --synthetic
python -m uvicorn app.main:app --port 8000 --env-file .env                      # API with keys

# Web
cd apps/web && npm ci && npm run dev        # mock mode (VITE_API_MODE=mock)
npm run dev:live                            # live mode against the API
npm run typecheck && npm run lint && npm run build
set PW_CHANNEL=chrome && npx playwright test   # smoke test 7 (uses the installed Chrome)
```
If port 8000 is busy, an old uvicorn is still running: stop it (`stop-demo` or Task Manager) before starting again.
The laptop is modest (2 cores, 10 GB RAM): run one heavy command (npm install, build, test run) at a time.

## CI checks (all must pass)
`integrity` (test lock, no data/secrets) -> `backend` (ruff + unit tests + 90% coverage on `core/rules`) -> `integration` -> `web` (typecheck, lint, build, smoke test).
