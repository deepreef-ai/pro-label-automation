#!/usr/bin/env bash
# POSIX twin of reset-demo.ps1. Usage: ./reset-demo.sh [--synthetic]
source "$(dirname "$0")/infra/demo/demo-lib.sh"
SYN=0; [ "${1:-}" = --synthetic ] && SYN=1
step "Stopping the demo"; stop_all
load_env
PY="$(venv_python)"
build_db "$PY" "$SYN"
step "Rebuilding the RAG index (data/rag)"
mkdir -p "$DATA/rag"; find "$DATA/rag" -maxdepth 1 -type f -delete
if "$PY" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('fastembed') else 1)"; then
  PYTHONPATH="$ROOT/apps/api" "$PY" -m chat.rag --build || warn "semantic build failed; keyword search will be used"
else
  PYTHONPATH="$ROOT/apps/api" CHAT_RAG_MODE=keyword "$PY" -m chat.rag "client lock" || warn "keyword index build failed"
fi
echo "Reset done. Start with ./run-demo.sh"
