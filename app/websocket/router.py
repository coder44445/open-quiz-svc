from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import logger
from app.domain.player.model import Player
from app.domain.game.answer import Answer
from app.domain.game.state import GameState
from app.services.game_service import GameService
from app.services.answer_service import AnswerService
from app.services.match_result import MatchResult
from app.websocket.event_gateway import EventGateway


router = APIRouter()
service = GameService()
answer_service = AnswerService()
event_gateway = EventGateway()


@router.websocket("/ws/{room_id}")
async def websocket_room(websocket: WebSocket, room_id: str) -> None:
    """Handle all WebSocket traffic for a single quiz room.

    Each connected client sends JSON messages with a ``type`` field that acts
    as a command discriminator.  Supported types:

    - ``join``   — register the player and receive a player_id
    - ``topic``  — submit a quiz topic
    - ``start``  — trigger AI question generation (transitions LOBBY → GENERATING)
    - ``begin``  — start the timed game loop (transitions READY → IN_PROGRESS)
    - ``answer`` — submit an answer for the current question
    - ``rejoin`` — sync state for a reconnecting client

    The game loop is intentionally started as an asyncio background task so
    this WebSocket can keep receiving messages (answers, rejoins, disconnects)
    while questions are ticking.  Unknown event types are logged and ignored.
    """

    await websocket.accept()

    # Subscribe this client to room-level Redis Pub/Sub events in the background.
    asyncio.create_task(event_gateway.subscribe(room_id, websocket))

    # player_id is populated after the client sends a "join" event.
    player_id: str | None = None

    # Track the running loop task to guard against duplicate begin events.
    loop_task: asyncio.Task | None = None

    log = logger.bind(room_id=room_id)
    log.info("websocket_client_connected")

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")

            log.debug("websocket_event_received", event_type=event_type, player_id=player_id)

            if event_type == "join":
                player = Player(name=data["user"])
                await service.add_player(room_id, player)

                # Capture the assigned player_id so subsequent logs include it.
                player_id = player.id
                log = log.bind(player_id=player_id)

                await websocket.send_json({
                    "type": "joined",
                    "player_id": player.id,
                })

            elif event_type == "topic":
                topic = data["text"]
                await service.add_topic(room_id, topic)

                await websocket.send_json({
                    "type": "topic_added",
                    "topic": topic,
                })

            elif event_type == "start":
                session = await service.start_game(room_id)

                await websocket.send_json({
                    "type": "game_starting",
                    "state": session.state.value,
                    "topic_count": len(session.topics),
                })

            elif event_type == "begin":
                # Prevent duplicate loops if the client sends begin more than once.
                if loop_task and not loop_task.done():
                    log.warning("begin_ignored_loop_already_running")
                    continue

                session = await service.begin_play(room_id)

                await websocket.send_json({
                    "type": "game_began",
                    "questions": len(session.questions),
                })

                # Run the game loop as a background task so this WebSocket
                # continues receiving messages while the loop ticks through
                # questions.  When finished, it pushes game_finished back
                # through this same WebSocket connection.
                async def _run_loop_and_notify(rid: str = room_id) -> None:
                    try:
                        result = await service.loop.run(rid)
                        if isinstance(result, MatchResult):
                            log.info(
                                "game_result_sending",
                                leaderboard_size=len(result.leaderboard),
                            )
                            await websocket.send_json({
                                "type": "game_finished",
                                "leaderboard": [
                                    {
                                        "player_id": p.player_id,
                                        "name": p.player_name,
                                        "score": p.score,
                                    }
                                    for p in result.leaderboard
                                ],
                            })
                    except Exception:
                        log.exception("game_loop_error")

                loop_task = asyncio.create_task(_run_loop_and_notify())

            elif event_type == "answer":
                session = await service.get_session(room_id)

                if not session:
                    log.warning("answer_ignored_no_session")
                    continue

                answer = Answer(
                    player_id=data["player_id"],
                    question_id=session.current_question_index,
                    selected_index=data["selected"],
                    time_taken=data.get("time_taken", 0),
                )

                try:
                    score = await answer_service.submit_answer(room_id, answer)
                except ValueError as exc:
                    # Non-fatal: duplicate or invalid answer — inform the client.
                    log.warning(
                        "answer_rejected",
                        player_id=data.get("player_id"),
                        reason=str(exc),
                    )
                    await websocket.send_json({"type": "answer_rejected", "reason": str(exc)})
                    continue

                await websocket.send_json({
                    "type": "answer_received",
                    "score": score,
                })

            elif event_type == "rejoin":
                session = await service.get_session(room_id)

                if not session:
                    log.warning("rejoin_ignored_no_session", player_id=player_id)
                    continue

                question = session.get_current_question()
                remaining = session.time_limit - (
                    int(time.time()) - session.question_started_at
                )

                log.info(
                    "client_rejoined",
                    state=session.state.value,
                    question_index=session.current_question_index,
                    time_remaining=max(0, remaining),
                )

                await websocket.send_json({
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

            else:
                # Log unknown event types so client bugs surface in the logs.
                log.warning("websocket_unknown_event_type", event_type=event_type)

    except WebSocketDisconnect:
        log.info("websocket_client_disconnected")
        # Cancel the loop task if the host disconnects mid-game.
        if loop_task and not loop_task.done():
            loop_task.cancel()
            log.info("game_loop_cancelled_on_disconnect")

    except Exception:
        log.exception("websocket_unhandled_error")
