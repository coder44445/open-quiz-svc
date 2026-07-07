from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

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
    await websocket.accept()

    asyncio.create_task(event_gateway.subscribe(room_id, websocket))

    logger.info("player_connected", room_id=room_id)

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")

            if event_type == "join":
                player = Player(name=data["user"])
                await service.add_player(room_id, player)

                await websocket.send_json({
                    "type": "joined",
                    "player_id": player.id,
                })

            elif event_type == "topic":
                await service.add_topic(room_id, data["text"])

                await websocket.send_json({
                    "type": "topic_added",
                    "topic": data["text"],
                })

            elif event_type == "start":
                session = await service.start_game(room_id)

                await websocket.send_json({
                    "type": "game_starting",
                    "state": session.state.value,
                    "topic_count": len(session.topics),
                })

            elif event_type == "begin":
                session = await service.begin_play(room_id)
                result = await service.loop.run(room_id)

                await websocket.send_json({
                    "type": "game_began",
                    "questions": len(session.questions),
                })

                if isinstance(result, MatchResult):
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

            elif event_type == "answer":
                session = await service.get_session(room_id)

                if not session:
                    continue

                answer = Answer(
                    player_id=data["player_id"],
                    question_id=session.current_question_index,
                    selected_index=data["selected"],
                    time_taken=data.get("time_taken", 0),
                )

                score = await answer_service.submit_answer(room_id, answer)

                await websocket.send_json({
                    "type": "answer_received",
                    "score": score,
                })

            elif event_type == "rejoin":
                session = await service.get_session(room_id)

                if not session:
                    continue

                question = session.get_current_question()
                remaining = session.time_limit - (
                    int(time.time()) - session.question_started_at
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

    except WebSocketDisconnect:
        logger.info("player_disconnected", room_id=room_id)

    except Exception as e:
        logger.error("websocket_error", room_id=room_id, error=str(e))
