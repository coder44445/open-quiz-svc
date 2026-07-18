# AI-Powered Real-Time Multiplayer Quiz Platform

## Overview

Production-ready backend for real-time multiplayer quiz games. Built with FastAPI (HTTP + WebSocket), Redis for runtime session state, PostgreSQL for durable persistence, and an isolated ARQ AI worker for generating quiz questions via Ollama.

Recent upgrades have stabilized the architecture for production, focusing on race-condition mitigation, performance profiling, and resilient state recovery.

## Highlights & Architecture

- **Secure REST Room Creation**: Room IDs are cryptographically generated via a standard REST API (`POST /api/game/create`) with internal collision retries, providing distinct separation between room establishment and WebSocket attachment.
- **Multiplexed Fan-Out WebSocket Gateway**: Deprecated the standard 1-Redis-PubSub-per-WebSocket pattern. A singleton `EventGateway` now multiplexes all clients for a given room onto exactly one Redis Pub/Sub subscription. Message broadcasting uses `asyncio.gather` for concurrent delivery, preventing slow clients from causing broadcast storms.
- **Reconnect-Safe Session Persistence**: WebSocket connection lifecycle is entirely decoupled from player identity. Clients can freely drop connection, refresh their browser, and seamlessly resume their session (`handle_rejoin`) without data loss or score resets.
- **Passive Memory Management (TTL)**: Long-running or abandoned rooms are automatically cleaned up via a 2-hour Redis TTL to prevent memory leaks in production.
- **AI Worker Dead-Room Protection**: The asynchronous ARQ worker constantly monitors room health during LLM batch generation. If a room is abandoned and its session is collected by the TTL, the AI worker instantly aborts generation to save compute resources.
- **Dynamic CORS & Configuration**: Fully integrated `pydantic-settings` allowing complete control over AI temperature, batch sizes, connection timeouts, and origin enforcement via `.env`.

## Quick Start

1. Create and activate a virtualenv:

```bash
uv venv
source .venv/bin/activate
uv sync
```

2. Configure your environment variables:

Copy the example environment file and customize it. The application uses `pydantic-settings` to automatically load variables from the `.env` file.

```bash
cp .env.example .env
```

**Required Infrastructure:**
- A running PostgreSQL instance
- A running Redis instance
- Ollama running locally or remotely

Example `.env` configuration:
```env
# Server
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS='["http://localhost:3000"]'

# Infrastructure 

# if Database and Redis are in you local
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/fastapi
REDIS_URL=redis://localhost:6379/0

# if you are using docker compose
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/fastapi
REDIS_URL=redis://redis:6379/0

# Game Logic
MAX_PLAYERS=20
MAX_TOPICS_PER_PLAYER=10
SELECTED_TOPICS_PER_GAME=5
QUESTION_TIME_LIMIT=60

# AI / LLM Configuration
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:4b
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=120
GENERATION_BATCH_SIZE=1
```

3. Apply DB migrations (ensure PostgreSQL is running):

```bash
.venv/bin/alembic -c alembic.ini upgrade head
```

4. Run the API and WebSockets server locally:

```bash
uvicorn app.main:app --reload
```

5. Run the background AI Worker:

In a separate terminal window, start the ARQ worker to process AI generation jobs:

```bash
arq app.ai.worker.WorkerSettings
```

## Development

- Run tests:

```bash
pytest -q
```

- Create an autogenerate migration:

```bash
.venv/bin/alembic -c alembic.ini revision --autogenerate -m "describe change"
```

## Important files

- `app/main.py` — application entry; registers routers and health/metrics
- `app/websocket/router.py` — WebSocket gateway and event handling
- `app/ai/worker.py` — AI worker job that generates and persists questions
- `app/infrastructure/redis/session_repository.py` — session runtime storage & rehydration
- `app/core/config.py` — environment schema and defaults
- `alembic/` — migration scripts

## Comprehensive Configuration

The application is highly configurable via the `.env` file. Notable keys include:

- **Infrastructure**: `DATABASE_URL` (PostgreSQL), `REDIS_URL`
- **Networking**: `HOST`, `PORT`, `CORS_ORIGINS` (JSON array of allowed frontend URLs)
- **Gameplay**: `MAX_PLAYERS`, `MAX_TOPICS_PER_PLAYER`, `SELECTED_TOPICS_PER_GAME`, `QUESTION_TIME_LIMIT`
- **AI/LLM Engine**:
  - `OLLAMA_HOST` & `OLLAMA_MODEL`
  - `LLM_TEMPERATURE` — Adjusts generation creativity (e.g., `0.2` for strictness, `0.9` for varied questions)
  - `GENERATION_BATCH_SIZE` — Number of questions to generate per LLM call
  - `TOTAL_QUESTIONS` — Target number of questions for a full game

## CI / Observability

- CI runs lint and tests in `.github/workflows/ci.yml`
- Metrics exposed at `/metrics` using `prometheus_client`

## Contribution & Next Steps

- Ensure migrations are committed after model changes
- Add end-to-end WebSocket + DB tests (recommended with docker-compose)
- Expand AI job observability and retry policies

Enjoy building — ask me to scaffold more docs, CI steps, or an integration test harness.
