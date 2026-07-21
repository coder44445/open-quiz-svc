from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.infrastructure.database.unit_of_work import UnitOfWork

router = APIRouter(prefix="/api/matches", tags=["matches"])


# Response schemas

class MatchSummary(BaseModel):
    id: int
    room_id: str
    finished_at: datetime | None
    total_players: int
    total_questions: int
    difficulty: str
    question_count: int


class PlayerResult(BaseModel):
    player_id: str
    name: str
    score: int
    correct_answers: int


class QuestionResult(BaseModel):
    order: int
    topic: str
    difficulty: str
    text: str
    options: list[str]
    correct_index: int


class AnswerDetail(BaseModel):
    player_id: str
    question_order: int
    selected_option: int
    score: int
    time_taken: float
    is_correct: bool


class MatchDetail(BaseModel):
    id: int
    room_id: str
    finished_at: datetime | None
    total_players: int
    total_questions: int
    difficulty: str
    question_count: int
    leaderboard: list[PlayerResult]
    questions: list[QuestionResult]
    answers: list[AnswerDetail]


# Endpoints

@router.get("", response_model=list[MatchSummary])
async def list_matches(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatchSummary]:
    """Return a paginated list of completed matches, newest first."""
    async with UnitOfWork() as uow:
        matches = await uow.matches.list_finished(limit=limit, offset=offset)
        return [
            MatchSummary(
                id=m.id,
                room_id=m.room_id,
                finished_at=m.finished_at,
                total_players=m.total_players,
                total_questions=m.total_questions,
                difficulty=m.difficulty,
                question_count=m.question_count,
            )
            for m in matches
        ]


@router.get("/{room_id}", response_model=MatchDetail)
async def get_match(room_id: str) -> MatchDetail:
    """Return the full breakdown for a single completed match."""
    async with UnitOfWork() as uow:
        match = await uow.matches.get_by_room(room_id)
        if not match or match.state != "finished":
            raise HTTPException(status_code=404, detail="Match not found")

        import asyncio
        players, questions, answers = await asyncio.gather(
            uow.matches.get_players(match.id),
            uow.matches.get_questions(match.id),
            uow.matches.get_answers(match.id)
        )

    # Build an order-index map for O(1) lookup when assembling answer details
    q_order_by_db_id = {q.id: q.order for q in questions}
    q_correct_by_db_id = {q.id: q.correct_index for q in questions}

    return MatchDetail(
        id=match.id,
        room_id=match.room_id,
        finished_at=match.finished_at,
        total_players=match.total_players,
        total_questions=match.total_questions,
        difficulty=match.difficulty,
        question_count=match.question_count,
        leaderboard=sorted(
            [
                PlayerResult(
                    player_id=mp.player_id,
                    name=mp.player.name if mp.player else mp.player_id,
                    score=mp.score,
                    correct_answers=mp.correct_answers,
                )
                for mp in players
            ],
            key=lambda p: p.score,
            reverse=True,
        ),
        questions=[
            QuestionResult(
                order=q.order,
                topic=q.topic,
                difficulty=q.difficulty,
                text=q.text,
                options=q.options,
                correct_index=q.correct_index,
            )
            for q in questions
        ],
        answers=[
            AnswerDetail(
                player_id=a.player_id,
                question_order=q_order_by_db_id.get(a.question_id, -1),
                selected_option=a.selected_option,
                score=a.score,
                time_taken=a.time_taken,
                is_correct=a.selected_option == q_correct_by_db_id.get(a.question_id, -1),
            )
            for a in answers
        ],
    )


@router.get("/player/{player_id}", response_model=list[MatchSummary])
async def get_player_history(
    player_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatchSummary]:
    """Return all finished matches a specific player participated in."""
    async with UnitOfWork() as uow:
        matches = await uow.matches.list_by_player(
            player_id=player_id, limit=limit, offset=offset
        )
        return [
            MatchSummary(
                id=m.id,
                room_id=m.room_id,
                finished_at=m.finished_at,
                total_players=m.total_players,
                total_questions=m.total_questions,
            )
            for m in matches
        ]
