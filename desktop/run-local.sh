#!/bin/bash
# Runs the whole Anvil stack locally in WSL, without Docker.
#
# Why not Docker: this machine has none, and the VPS deploy is a separate
# problem. Postgres, Redis and Python run natively in WSL instead; the schema
# comes from the same db/init.sql the container image bakes in, so local and
# server run identical SQL.
#
#   bash run-local.sh start   — start everything
#   bash run-local.sh stop    — stop everything
#   bash run-local.sh status  — what's up, and is it answering

REPO="/mnt/c/Users/mikus/OneDrive/Dokumente/Agentic Workflow/ai-company"
VENV="$HOME/anvil-venv"
LOGS="$HOME/anvil-logs"

export DATABASE_URL="postgresql+psycopg://factory:factory@localhost:5432/factory"
export REDIS_URL="redis://localhost:6379/0"
# Blank = no auth. Local-only: the API binds 127.0.0.1 and nothing forwards a
# port to it. Do not copy this to anything reachable from outside.
export API_KEY=""
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
export PYTHONPATH="$REPO/backend"

mkdir -p "$LOGS"

start() {
  sudo service postgresql start >/dev/null 2>&1
  sudo service redis-server start >/dev/null 2>&1

  if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "Warnung: OPENROUTER_API_KEY ist leer — Agenten und Chat können nicht denken."
  fi

  cd "$REPO/backend"
  nohup "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 \
    > "$LOGS/backend.log" 2>&1 &
  echo "backend      -> $LOGS/backend.log"

  nohup "$VENV/bin/celery" -A app.celery_app worker --loglevel=INFO --concurrency=6 \
    > "$LOGS/worker.log" 2>&1 &
  echo "celery worker-> $LOGS/worker.log"

  nohup "$VENV/bin/celery" -A app.celery_app beat --loglevel=INFO \
    > "$LOGS/beat.log" 2>&1 &
  echo "celery beat  -> $LOGS/beat.log"

  sleep 6
  status
}

stop() {
  pkill -f "uvicorn app.main:app" 2>/dev/null && echo "backend gestoppt"
  pkill -f "celery -A app.celery_app" 2>/dev/null && echo "celery gestoppt"
  true
}

status() {
  echo "--- Prozesse ---"
  pgrep -af "uvicorn app.main:app" | head -2 || echo "backend: laeuft nicht"
  pgrep -af "celery -A app.celery_app worker" | head -1 || echo "worker: laeuft nicht"
  pgrep -af "celery -A app.celery_app beat" | head -1 || echo "beat: laeuft nicht"
  echo "--- antwortet die API? ---"
  curl -s -o /dev/null -w "  /health -> HTTP %{http_code}\n" --max-time 5 http://127.0.0.1:8000/health
  curl -s --max-time 5 http://127.0.0.1:8000/api/dashboard/overview | head -c 200
  echo
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}" ;;
esac
