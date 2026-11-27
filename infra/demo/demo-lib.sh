# Shared helpers for run-demo.sh / reset-demo.sh / stop-demo.sh (sourced). macOS / Linux / Git Bash.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA="$ROOT/data"
PIDS="$DATA/demo.pids"
LOGS="$DATA/logs"
cd "$ROOT"

step() { printf '==> %s\n' "$*"; }
warn() { printf '    WARNING: %s\n' "$*"; }

load_env() {  # .env values do not override variables already set
  [ -f "$ROOT/.env" ] || { warn ".env not found; using defaults"; return 0; }
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|\#*) continue ;; esac
    k="${line%%=*}"; v="${line#*=}"
    k="$(echo "$k" | tr -d '[:space:]')"
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    [ -n "$k" ] && [ -z "${!k:-}" ] && export "$k=$v"
  done < "$ROOT/.env"
  return 0
}

venv_python() {  # DEMO_VENV=<existing venv> skips creation and installs
  if [ -n "${DEMO_VENV:-}" ]; then
    for p in "$DEMO_VENV/bin/python" "$DEMO_VENV/Scripts/python.exe"; do [ -x "$p" ] && { echo "$p"; return; }; done
    echo "DEMO_VENV has no python" >&2; exit 1
  fi
  local venv="$ROOT/.venv" py
  [ -d "$venv" ] || { step "Creating .venv" >&2; python3 -m venv "$venv" >&2; }
  py="$venv/bin/python"; [ -x "$py" ] || py="$venv/Scripts/python.exe"
  if [ ! -f "$venv/.demo-installed" ] || [ "$ROOT/apps/api/requirements.txt" -nt "$venv/.demo-installed" ]; then
    step "Installing API requirements" >&2
    "$py" -m pip install -q --disable-pip-version-check -r "$ROOT/apps/api/requirements.txt" >&2
    date > "$venv/.demo-installed"
  fi
  echo "$py"
}

node_modules() {
  local web="$ROOT/apps/web"
  if [ ! -f "$web/node_modules/.package-lock.json" ] || [ "$web/package-lock.json" -nt "$web/node_modules/.package-lock.json" ]; then
    step "npm ci (first run only)"; (cd "$web" && npm ci --no-audit --no-fund)
  fi
}

sqlite_path() {
  local url="${DATABASE_URL:-sqlite:///data/demo.db}"
  case "$url" in sqlite:///*) p="${url#sqlite:///}"; case "$p" in /*) echo "$p" ;; *) echo "$ROOT/$p" ;; esac ;; *) echo "" ;; esac
}

build_db() {  # $1 = python, $2 = 1 for synthetic
  local args=(-m core.etl.build_demo_db)
  if [ "${2:-0}" = 1 ] || [ ! -d "$DATA/raw" ]; then args+=(--synthetic); fi
  step "Building demo database ${args[*]:2}"
  PYTHONPATH="$ROOT/apps/api" "$1" "${args[@]}"
}

stop_all() {
  [ -f "$PIDS" ] || { echo "    no demo processes recorded"; return 0; }
  while read -r name pid _; do
    [ -n "${pid:-}" ] || continue
    if kill -0 "$pid" 2>/dev/null; then
      if [ -r "/proc/$pid/winpid" ] && command -v taskkill >/dev/null; then  # Git Bash: kill the Windows tree
        taskkill //PID "$(cat "/proc/$pid/winpid")" //T //F >/dev/null 2>&1 || true
      fi
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      echo "    stopped $name (PID $pid)"
    fi
  done < "$PIDS"
  rm -f "$PIDS"
}

wait_url() {  # url seconds
  local i=0
  while [ "$i" -lt "$(( $2 * 2 ))" ]; do curl -fsS -o /dev/null "$1" 2>/dev/null && return 0; sleep 0.5; i=$((i + 1)); done
  return 1
}

# Demo logins (SPEC 6, contract/README.md): OTP is always 123456 in the demo.
print_logins() {
  echo "  Logins (OTP 123456):"
  echo "    Pro Labels owner     company prolabels      +91 90000 00001"
  echo "    Pro Labels store     company prolabels      +91 90000 00005"
  echo "    Sunrise Flexo owner  company sunriseflexo   +91 90000 00201"
  echo "    Nilgiri Labels owner company nilgirilabels  +91 90000 00301"
  echo "    Platform admin       (no company)           admin@platform.example"
}

