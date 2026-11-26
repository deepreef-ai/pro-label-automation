# infra

Demo scripts, Dockerfiles and compose now; AWS later after client approval (owner: Yash).

## One-command demo (Windows laptop)

Prerequisites: Python 3.11+, Node.js 20+, optional Ollama (only for `AI_MODE=local`).

```bat
copy .env.example .env        & rem add your free API keys
run-demo.cmd                  & rem or: powershell -File run-demo.ps1
stop-demo.cmd
reset-demo.cmd [-Synthetic]   & rem before a rehearsal
```

| Script | What it does |
|---|---|
| `run-demo` | Loads `.env`; creates `.venv` + `pip install -r apps/api/requirements.txt` and runs `npm ci` only when missing or out of date; builds `data/demo.db` if missing (from `data/raw`, else synthetic); starts the API (uvicorn, port 8000) and the web dev server (Vite in live mode, port 5173, `VITE_API_URL` pointing at the API) in the background; starts `ollama serve` when `AI_MODE=local` and it is not already running; waits for `GET /api/health`; opens the browser. |
| `stop-demo` | Stops exactly the processes listed in `data/demo.pids`, with their child processes. |
| `reset-demo` | `stop-demo`, rebuilds the DB (`core.etl.build_demo_db`, `-Synthetic` passed through) and the chat RAG index in `data/rag/` (semantic vectors when `fastembed` from `apps/api/requirements-ai.txt` is installed, else the keyword index; the downloaded model is kept). |

`run-demo.ps1` options: `-Mock` (web on contract fixtures), `-NoBrowser`, `-Synthetic`, `-ApiPort`, `-WebPort`.
Environment: `DEMO_VENV=<path>` uses an existing virtualenv (no creation, no installs). Variables already set in the shell win over `.env`.

Logs: `data/logs/api.log`, `web.log`, `ollama.log`. First run takes a few minutes (installs); later runs start in under 10 s.

The scripts are Windows PowerShell 5.1 compatible. `run-demo.sh` / `stop-demo.sh` / `reset-demo.sh` are the same for macOS / Linux (`--mock`, `--synthetic`, `--no-browser`). Shared code lives in `infra/demo/`.

## Docker (optional, not needed on the laptop)

```bash
docker compose -f infra/docker-compose.yml up --build
# web http://localhost:8080 (nginx, proxies /api and /openapi.json to the api service)
# api http://localhost:8000
```

- `api.Dockerfile`: python:3.11-slim, non-root user, `HEALTHCHECK` on `/api/health`; builds a synthetic DB on first start when `data/demo.db` is missing.
- `web.Dockerfile`: Node build (`npm run build:live`, build arg `VITE_API_URL`, default `http://localhost:8080`) then nginx with `nginx.conf`.
- `docker-compose.yml`: `env_file: ../.env`, `../data` bind-mounted to `/app/data`; `OLLAMA_URL` points at the Docker host (`OLLAMA_URL_DOCKER` overrides it); `WEB_PUBLIC_URL` sets the web build's API URL.
- The root `.dockerignore` keeps `data/`, `.env`, `*.db`, `.venv` and `node_modules` out of every image.

## Agents scheduler (per company)

```bash
PYTHONPATH=apps/api python -m agents.scheduler            # loop: import_checker every 15 min, all agents 08:00, owner brief 09:00 (IST)
PYTHONPATH=apps/api python -m agents.scheduler --once     # run all agents for every company now, then exit
PYTHONPATH=apps/api python -m agents.scheduler --once --company CO-002
```

- Companies with status `paused` are skipped. Each company runs in its own scoped session
  (`core.tenancy.scoped`), so runs (`AR-`), findings (`F-`), outbox (`OB-`) and audit rows get that
  company's `company_id` and ids are numbered per company (CO-001 and CO-002 can both have `AR-0420`).
- Log lines are prefixed with the company: `[CO-002] AR-5420 import_checker: ok, 1 new (...)`.
  `--once` exits 1 if any run failed. Uses `DATABASE_URL` like the API (SQLite by default).

## PostgreSQL + row-level security (optional)

```bash
docker compose -f infra/docker-compose.postgres.yml up --build
# API http://localhost:8000 on Postgres; reset: docker compose -f infra/docker-compose.postgres.yml down -v
```

| Service | What it does |
|---|---|
| `db` | `postgres:16`, database `labels`, owner `labels` (`PG_OWNER_PASSWORD`, default `labels`), volume `pgdata`. |
| `init` | One shot, as the owner: `infra/postgres/init_rls.py` builds the synthetic demo data (first run only; `--rebuild` to start over), applies `core.tenancy.rls_statements` (ENABLE + FORCE RLS, policy `company_isolation` on `current_setting('app.company_id', true)`), creates the API role `label_app` (`PG_APP_PASSWORD`; `NOSUPERUSER NOBYPASSRLS`, DML grants only) and self-checks as that role: no company set = no rows, each company sees only its own rows. Non-zero exit = RLS does not bite, and the API does not start. |
| `api` | `DATABASE_URL=postgresql+psycopg://label_app:...@db:5432/labels`. Never connect the API as the owner/superuser: superusers bypass RLS. |
| `scheduler` | `python -m agents.scheduler --company all` against the same database. |

How the company reaches Postgres: on PostgreSQL every transaction of a scoped engine starts with
`SELECT set_config('app.company_id', '<CO-xxx>', false)` (hook in `core/tenancy.py`; an unscoped
connection sets `''` and so sees no company rows). The SQL filter from `scoped()` still runs too,
so RLS is a second wall, not the only one. SQLite (the laptop demo) is unchanged.
Platform tables (`companies`, `users`) have no RLS; platform-wide reports over company tables must
loop over companies with a scoped connection each.
