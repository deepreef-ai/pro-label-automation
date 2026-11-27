#!/usr/bin/env bash
# POSIX twin of run-demo.ps1. Usage: ./run-demo.sh [--mock] [--synthetic] [--no-browser] [--postgres]
source "$(dirname "$0")/infra/demo/demo-lib.sh"
API_PORT="${API_PORT:-8000}"; WEB_PORT="${WEB_PORT:-5173}"; MOCK=0; SYN=0; BROWSER=1; PG=0
for a in "$@"; do case "$a" in --mock) MOCK=1 ;; --synthetic) SYN=1 ;; --no-browser) BROWSER=0 ;; --postgres) PG=1 ;; esac; done
[ -f "$PIDS" ] && { warn "demo already running? run ./stop-demo.sh first"; exit 1; }
load_env
PY="$(venv_python)"
node_modules
DB="$(sqlite_path)"; [ "$PG" = 0 ] && [ -n "$DB" ] && [ ! -f "$DB" ] && build_db "$PY" "$SYN"
mkdir -p "$LOGS"
if [ "$(echo "${AI_MODE:-cloud}" | tr '[:upper:]' '[:lower:]')" = local ]; then
  base="${OLLAMA_URL:-http://localhost:11434/v1}"; base="${base%/v1}"
  if ! curl -fsS -o /dev/null "$base/api/tags" 2>/dev/null; then
    if command -v ollama >/dev/null; then ollama serve > "$LOGS/ollama.log" 2>&1 & echo "ollama $! 0" >> "$PIDS"
    else warn "AI_MODE=local but Ollama is not installed; AI falls back to deterministic text"; fi
  fi
fi
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT}"
if [ "$PG" = 1 ]; then  # PostgreSQL + row-level security, API and scheduler in Docker (B3)
  command -v docker >/dev/null || { warn "--postgres needs Docker (docker compose)"; exit 1; }
  API_PORT=8000
  step "Starting PostgreSQL + RLS, API and scheduler (docker compose)"
  docker compose -f "$ROOT/infra/docker-compose.postgres.yml" up -d --build || { warn "docker compose failed"; exit 1; }
else
  step "Starting API on http://localhost:$API_PORT"
  PYTHONPATH="$ROOT/apps/api" nohup "$PY" -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port "$API_PORT" > "$LOGS/api.log" 2>&1 &
  echo "api $! 0" >> "$PIDS"
fi
mode=(--mode live); export VITE_API_MODE=live VITE_API_URL="http://localhost:$API_PORT"
[ "$MOCK" = 1 ] && { mode=(); export VITE_API_MODE=mock; }
step "Starting web on http://localhost:$WEB_PORT ($VITE_API_MODE)"
cd "$ROOT/apps/web"
nohup node node_modules/vite/bin/vite.js --port "$WEB_PORT" --strictPort "${mode[@]}" > "$LOGS/web.log" 2>&1 &
echo "web $! 0" >> "$PIDS"
cd "$ROOT"
wait_url "http://localhost:$API_PORT/api/health" "$([ "$PG" = 1 ] && echo 600 || echo 90)" || { warn "API not healthy; see data/logs/api.log"; stop_all; exit 1; }
wait_url "http://localhost:$WEB_PORT" 60 || { warn "web not ready; see data/logs/web.log"; stop_all; exit 1; }
if [ "$BROWSER" = 1 ]; then (command -v xdg-open >/dev/null && xdg-open "http://localhost:$WEB_PORT" || open "http://localhost:$WEB_PORT") >/dev/null 2>&1 || true; fi
echo "Demo is running: web http://localhost:$WEB_PORT  api http://localhost:$API_PORT  stop: ./stop-demo.sh"
print_logins
