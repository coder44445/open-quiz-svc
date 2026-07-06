#!/usr/bin/env bash
set -euo pipefail

echo "Starting docker-compose stack for integration tests..."
docker compose up --build -d

echo "Waiting for app to become healthy..."
for i in {1..60}; do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "App is healthy"
    break
  fi
  echo "waiting... ($i)"
  sleep 1
done

echo "Running integration tests (INTEGRATION=1)..."
INTEGRATION=1 pytest tests/integration -q

EXIT_CODE=$?

echo "Tearing down compose stack..."
docker compose down

exit $EXIT_CODE
