from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field

import structlog
from fastapi import WebSocket

from app.domain.player.model import Player
from app.domain.game.answer import Answer
from app.services.game_service import GameService
from app.services.answer_service import AnswerService
from app.infrastructure.events.event_bus import GameEventBus
from app.domain.events import GameEvent
from app.domain.event_types import EventType
from app.websocket.schemas import (
    JoinEvent, TopicEvent, StartEvent, BeginEvent, AnswerEvent, RejoinEvent, ForceStartEvent
)

logger = structlog.get_logger(__name__)

# Create static service instances
game_service = GameService()
answer_service = AnswerService()
event_bus = GameEventBus()

# Module-level registry of running game loop tasks keyed by room_id.
# This ensures only one loop runs per room regardless of which client
# sends the begin event, and survives host disconnects.
_active_loops: dict[str, asyncio.Task] = {}


@dataclass
class ConnectionContext:
    """Holds connection-specific state to pass between handlers."""
    room_id: str
    websocket: WebSocket
    player_id: str | None = None
    loop_task: asyncio.Task | None = None
    log: structlog.BoundLogger = field(init=False)

    def __post_init__(self):
        self.log = logger.bind(room_id=self.room_id)


class WebSocketEventHandlers:
    """Encapsulates the event logic for the quiz room WebSocket."""

    @staticmethod
    async def handle_join(ctx: ConnectionContext, payload: JoinEvent) -> None:
        player = Player(name=payload.user)
        await game_service.add_player(ctx.room_id, player)

        ctx.player_id = player.id
        ctx.log = ctx.log.bind(player_id=ctx.player_id)

        await ctx.websocket.send_json({
            "type": "joined",
            "player_id": player.id,
        })

    @staticmethod
    async def handle_topic(ctx: ConnectionContext, payload: TopicEvent) -> None:
        await game_service.add_topic(ctx.room_id, payload.text, ctx.player_id)

        # Broadcast to ALL clients in the room so everyone sees the topic appear.
        await event_bus.publish(GameEvent(
            type=EventType.TOPIC_ADDED,
            room_id=ctx.room_id,
            payload={"topic": payload.text},
        ))

    @staticmethod
    async def handle_force_start(ctx: ConnectionContext, payload: ForceStartEvent) -> None:
        """Host manually triggers game start with whatever topics exist so far."""
        session = await game_service.get_session(ctx.room_id)
        if not session:
            ctx.log.warning("force_start_ignored_no_session")
            return

        from app.domain.game.state import GameState
        if session.state != GameState.LOBBY:
            ctx.log.warning("force_start_ignored_wrong_state", state=session.state.value)
            return

        # Clear pending list so the auto-start guard doesn't block us
        session.pending_topic_submitters = []
        if not session.topics:
            session.topics = ["General Knowledge"]
        from app.infrastructure.redis.session_repository import SessionRepository
        await SessionRepository().save(session)

        await event_bus.publish(GameEvent(
            type=EventType.TOPICS_COLLECTED,
            room_id=ctx.room_id,
            payload={"pending_remaining": 0, "forced": True},
        ))
        try:
            await game_service.start_game(ctx.room_id)
        except Exception as e:
            ctx.log.warning("force_start_failed", error=str(e))

    @staticmethod
    async def handle_start(ctx: ConnectionContext, payload: StartEvent) -> None:
        try:
            await game_service.request_topics(ctx.room_id)
        except Exception as e:
            ctx.log.warning("request_topics_failed", error=str(e))

    @staticmethod
    async def handle_begin(ctx: ConnectionContext, payload: BeginEvent) -> None:
        # Prevent duplicate loops per room using the module-level registry.
        existing = _active_loops.get(ctx.room_id)
        if existing and not existing.done():
            ctx.log.warning("begin_ignored_loop_already_running")
            return

        session = await game_service.begin_play(ctx.room_id)

        # Notify the host immediately so the UI transitions.
        await ctx.websocket.send_json({
            "type": "game_began",
            "questions": len(session.questions),
        })

        async def _run_loop(rid: str = ctx.room_id) -> None:
            try:
                await game_service.loop.run(rid)
            except Exception:
                ctx.log.exception("game_loop_error", room_id=rid)
            finally:
                _active_loops.pop(rid, None)

        # Register and start — the loop broadcasts everything via event bus,
        # so no per-connection WebSocket writes happen here.
        task = asyncio.create_task(_run_loop())
        _active_loops[ctx.room_id] = task
        ctx.loop_task = task

    @staticmethod
    async def handle_answer(ctx: ConnectionContext, payload: AnswerEvent) -> None:
        session = await game_service.get_session(ctx.room_id)
        if not session:
            ctx.log.warning("answer_ignored_no_session")
            return

        answer = Answer(
            player_id=payload.player_id,
            question_id=session.current_question_index,
            selected_index=payload.selected,
            time_taken=payload.time_taken,
        )

        try:
            score = await answer_service.submit_answer(ctx.room_id, answer)
        except ValueError as exc:
            # Non-fatal: duplicate or invalid answer
            ctx.log.warning("answer_rejected", player_id=payload.player_id, reason=str(exc))
            await ctx.websocket.send_json({"type": "answer_rejected", "reason": str(exc)})
            return

        await ctx.websocket.send_json({
            "type": "answer_received",
            "score": score,
        })

    @staticmethod
    async def handle_rejoin(ctx: ConnectionContext, payload: RejoinEvent) -> None:
        session = await game_service.get_session(ctx.room_id)
        if not session:
            ctx.log.warning("rejoin_ignored_no_session", player_id=ctx.player_id)
            return

        question = session.get_current_question()
        remaining = session.time_limit - (
            int(time.time()) - session.question_started_at
        )

        ctx.log.info(
            "client_rejoined",
            state=session.state.value,
            question_index=session.current_question_index,
            time_remaining=max(0, remaining),
        )

        await ctx.websocket.send_json({
            "type": "game_state_sync",
            "state": session.state.value,
            "current_question_index": session.current_question_index,
            "question": asdict(question) if question else None,
            "time_remaining": max(0, remaining),
            "leaderboard": [
                {
                    "player_id": p.id,
                    "score": p.score,
                }
                for p in session.players.values()
            ],
        })
