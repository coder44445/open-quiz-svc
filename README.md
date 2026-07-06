# AI-Powered Real-Time Multiplayer Quiz Platform

## Overview

Production-ready backend for real-time multiplayer quiz games. Built with FastAPI (HTTP + WebSocket), Redis for runtime session state, PostgreSQL for durable persistence, and an isolated AI worker for generating quiz questions.

Key themes: recoverable state, clear domain boundaries, and safe AI job isolation.

## Highlights

- WebSocket-first architecture for low-latency gameplay
- Redis-backed `GameSession` with checkpointing and rehydration
- Durable storage of matches, questions, answers, and players in PostgreSQL
- Async AI generation worker (Ollama provider) that persists validated questions
- Prometheus metrics for AI job lifecycle and observability

## Quick Start

1. Create and activate a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Set environment variables (example):

```bash
export DATABASE_URL=sqlite+aiosqlite:///./dev.db
export REDIS_URL=redis://localhost:6379/0
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=gemma3
```

3. Apply DB migrations:

```bash
.venv/bin/alembic -c alembic.ini upgrade head
```

4. Run the app locally:

```bash
uvicorn app.main:app --reload
```

## Development

- Run tests:

```bash
pytest -q
```

- Create an autogenerate migration:

```bash
DATABASE_URL=sqlite+aiosqlite:///./dev.db .venv/bin/alembic -c alembic.ini revision --autogenerate -m "describe change"
```

## Important files

- `app/main.py` — application entry; registers routers and health/metrics
- `app/websocket/router.py` — WebSocket gateway and event handling
- `app/ai/worker.py` — AI worker job that generates and persists questions
- `app/infrastructure/redis/session_repository.py` — session runtime storage & rehydration
- `alembic/` — migration scripts

## Environment variables

- `DATABASE_URL` — SQLAlchemy URL for your DB
- `REDIS_URL` — Redis connection URL
- `OLLAMA_HOST` & `OLLAMA_MODEL` — Ollama LLM endpoint and model

## CI / Observability

- CI runs lint and tests in `.github/workflows/ci.yml`
- Metrics exposed at `/metrics` using `prometheus_client`

## Contribution & Next Steps

- Ensure migrations are committed after model changes
- Add end-to-end WebSocket + DB tests (recommended with docker-compose)
- Expand AI job observability and retry policies

Enjoy building — ask me to scaffold more docs, CI steps, or an integration test harness.
