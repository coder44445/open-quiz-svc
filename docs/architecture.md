# Application Architecture

This document describes the high-level architecture of the real-time Quiz application.

## Core Components

The application is split into two primary processes:
1. **FastAPI Web Server**: Handles REST API requests, WebSocket connections, and orchestrates the game loop.
2. **ARQ Background Worker**: Handles long-running AI tasks (e.g., generating quiz questions via Ollama).

## State Management (Dual-State Architecture)

The system is designed for massive horizontal scalability, using two data stores:

### 1. Redis (Ephemeral / Fast State)
- **Purpose**: Powers real-time gameplay.
- **Why**: The game loop runs at sub-second intervals (e.g., broadcasting time left, score updates, player joins/leaves). Writing this to PostgreSQL would cause massive write-contention.
- **Usage**: Active `GameSession`s are serialized and stored in Redis with a 2-hour TTL.
- **Access**: Any web server pod can fetch the session from Redis, making the WebSocket connections stateless.

### 2. PostgreSQL (Durable / Persistent State)
- **Purpose**: Powers analytics, history, and fault tolerance.
- **Usage**: When a match finishes, the final results (Answers, Match statistics, Leaderboard) are persisted here.
- **Rehydration**: If Redis crashes or evicts a session mid-game, the application detects a cache miss and *rehydrates* the exact `GameSession` state from PostgreSQL, ensuring zero data loss for active players.

## Game Loop & WebSockets

- **Game Event Bus**: Built on `asyncio.Queue` (with Redis Pub/Sub capabilities), it decouples the game engine from the WebSocket layer. The `GameLoop` publishes events (e.g., `QUESTION_READY`, `SCORE_UPDATED`), and the WebSocket endpoints subscribe to these events and push them to connected clients.
- **The Loop**: An independent background task (`app.services.game_loop.GameLoop`) runs continuously during the `IN_PROGRESS` state, managing timers, checking for all-player submissions, and transitioning questions automatically.

## AI Generation (ARQ & Ollama)

Question generation is slow and non-deterministic.
- When a game starts, the FastAPI server enqueues a generation job to Redis.
- The ARQ worker picks it up and calls the local Ollama instance (or a remote provider).
- **Batching**: The worker generates questions in small chunks (e.g., 2 at a time) to prevent the LLM from overflowing its context window or generating malformed JSON.
- **Concurrent Verification**: After generation, the ARQ worker uses `asyncio.gather` to concurrently ask the LLM to verify every question's correctness, massively reducing latency while maintaining high accuracy.
- **Streaming**: As questions pass validation, the worker publishes `QUESTION_READY` events to the Event Bus, allowing the frontend to show progress or even start the game before all questions are finished generating.
