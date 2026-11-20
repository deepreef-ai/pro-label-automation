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
