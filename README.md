# Open Quiz Backend (FastAPI + AI Engine)

This is the highly concurrent, event-driven backend for the Open Quiz real-time multiplayer platform. It uses FastAPI for REST/WebSocket traffic, Redis for sub-millisecond state management and Pub/Sub, PostgreSQL for permanent records, and ARQ for asynchronous AI question generation via Ollama.

## 🏗️ Architecture & "Why" Decisions

* **Multiplexed WebSocket Gateway:** Instead of spawning a dedicated Redis Pub/Sub listener for *every single* connected WebSocket (which crashes Redis under high load), we use a singleton `EventGateway`. It creates exactly *one* Redis listener per active room, and multiplexes incoming messages to all connected clients in memory using `asyncio.gather`. 
* **State Recovery & Reconnects:** Mobile browsers constantly drop WebSockets when the screen turns off. To prevent players from being kicked out, the WebSocket connection lifecycle is entirely decoupled from the actual `Player` state. A player can drop and reconnect, passing a `rejoin` event, and immediately receive the current game state without losing their score.
* **Passive Memory Management:** Rooms are stored entirely in Redis for speed. To prevent memory leaks when users simply close their browser without clicking "Leave", all rooms have a 2-hour sliding TTL (Time to Live). Redis passively deletes abandoned rooms.
* **Asynchronous AI Worker (ARQ):** Generating 15 questions via an LLM takes time (30+ seconds). Doing this inside a web request blocks the server. Instead, we push a job to Redis. A background ARQ worker picks it up, generates the questions, and directly pushes WebSocket events (`JOB_PROGRESS`, `JOB_COMPLETED`) to the clients so they see a live loading bar.

---

## 🛠️ Setup Guide: Local Development (Hot-Reload)

Use this setup when you are writing code and want instant hot-reloading. **Do not use Docker for the FastAPI app itself during development.**

### 1. Prerequisites
You need a database, Redis, and Ollama running. The easiest way is to use Docker for just the infrastructure:
```bash
# This starts Postgres and Redis locally
docker compose up db redis -d
```

### 2. Environment Setup (uv)
We use `uv` (a blazing fast Python package manager) instead of standard `pip` or `poetry`.
```bash
# Create virtual environment and sync dependencies
uv venv
source .venv/bin/activate
uv sync
```

### 3. Configuration
Copy the environment template:
```bash
cp .env.example .env
```
Ensure your `.env` points to your local infrastructure (e.g., `localhost`). If you are exposing your local server to the internet using **Microsoft Dev Tunnels** so friends can play, ensure your `CORS_ORIGINS` includes your Dev Tunnel frontend URL.

### 4. Database Migrations
Create the SQL tables:
```bash
uv run alembic -c alembic.ini upgrade head
```

### 5. Start the Servers
You need two terminal windows running simultaneously:

**Terminal A: The Web Server**
```bash
uvicorn app.main:app --reload
```

**Terminal B: The AI Background Worker**
```bash
uv run arq app.ai.worker.WorkerSettings
```

---

## 🚀 Setup Guide: Production Deployment (Docker)

When deploying to a real server (VPS), you run everything inside Docker containers so it stays online forever and automatically restarts on failure.

1. **Configure Environment:** Update the `.env` file to use Docker's internal networking hostnames (e.g., `db` instead of `localhost`):
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/fastapi
REDIS_URL=redis://redis:6379/0
# Assuming Ollama runs on the host machine, use the Docker bridge IP
OLLAMA_HOST=http://172.17.0.1:11434 
```

2. **Deploy the Stack:**
```bash
# Builds the images and starts API, Worker, Redis, and Postgres in the background
docker compose up --build -d
```

3. **Check Logs:**
```bash
# View backend logs
docker compose logs -f app

# View AI worker logs
docker compose logs -f worker
```

## 📂 Codebase Geography

* `app/websocket/router.py`: The entry point for all socket messages.
* `app/websocket/handlers.py`: The business logic. **Intent Note:** Notice that mutations are wrapped in `async with game_service.store.get_lock()`. This prevents a race condition where two players answer a question at the exact same millisecond, read the same state, and overwrite each other's updates.
* `app/services/game_loop.py`: An infinite `asyncio` loop that manages the active countdown timer and transitions the game phase (Lobby → Progress → Finished).
* `app/ai/worker.py`: The ARQ consumer that asks Ollama for questions, parses the JSON, and writes to the DB.
