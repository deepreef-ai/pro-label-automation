# infra

Demo scripts, Dockerfiles and compose now; AWS later after client approval (owner: Ravi).

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
