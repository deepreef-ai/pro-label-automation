# CLAUDE.md: rules for every Claude session working in this repo

Two developers (Vinay and Ravi) each work with their own Claude. Both Claudes follow this file.

## What this project is
A demo of an AI-powered operations system for a label-printing plant: one web app (12 screens), a chatbot and AI agents, replacing 11 linked Excel workbooks. Read `contract/SPEC.md` first: it holds the business rules, the endpoint list and the conventions. `contract/openapi.yaml`, `contract/schema.md` and `contract/fixtures/` expand it.

## Who owns what (edit only your owner's folders)
| Folder | Owner |
|---|---|
| `apps/web/`, `apps/api/chat/` | Vinay (frontend + chatbot) |
| `apps/api/app/`, `apps/api/agents/`, `infra/` | Ravi (backend API + agents) |
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

## Hard rules
- The repo is **PUBLIC**: never commit client files, `data/`, `.env`, keys, `*.db`, `*.xlsx`. Real client data lives only in the local, git-ignored `data/raw/`.
- Never edit, skip or weaken tests to make a PR pass (`skip`, `xfail`, `.only` and lowering coverage fail CI).
- All money, stock and tolerance maths goes through `core.rules` (never re-implement it, never let an LLM compute it).
- All LLM calls go through `core.llm.get_gateway()` (free providers with fallback; anonymised in cloud mode). If the LLM is unavailable, fall back to deterministic text: the demo must never break.
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

## Running things
```bash
# Python (from repo root)
python -m venv .venv && .venv\Scripts\activate
pip install -r apps/api/requirements.txt -r requirements-dev.txt
set PYTHONPATH=apps/api
python -m core.etl.extract --raw data/raw --out data/extract   # needs the client files locally
pytest tests/unit -q                                            # rules engine (locked)
pytest tests/integration -q                                     # contract, demo flow, AI safety (locked)

# Web
cd apps/web && npm ci && npm run dev        # mock mode by default (VITE_API_MODE=mock)
npm run typecheck && npm run lint && npm run build
```
The laptop is modest (2 cores, 10 GB RAM): run one heavy command (npm install, build, test run) at a time.

## CI checks (all must pass)
`integrity` (test lock, no data/secrets) -> `backend` (ruff + unit tests + 90% coverage on `core/rules`) -> `integration` -> `web` (typecheck, lint, build, smoke test).
