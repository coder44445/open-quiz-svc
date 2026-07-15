#!/usr/bin/env sh
set -e

echo "Starting container, running migrations if DATABASE_URL is configured..."
if [ -n "${DATABASE_URL}" ]; then
  echo "Running alembic upgrade head"
  alembic -c alembic.ini upgrade head
fi

echo "Launching Uvicorn"
# Support development live-reload when UVICORN_RELOAD is truthy
RELOAD_FLAG=""
if [ "${UVICORN_RELOAD:-0}" = "1" ] || [ "${UVICORN_RELOAD:-}" = "true" ]; then
  RELOAD_FLAG="--reload"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${UVICORN_WORKERS:-1} ${RELOAD_FLAG}
