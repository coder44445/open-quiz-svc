from __future__ import annotations

from app.domain.game.state import GameState


class InvalidStateTransition(Exception):
    pass


class GameStateController:
    """
    Controls all allowed state transitions for a game session.

    This prevents invalid flows like:
    - starting game before questions are ready
    - answering before game starts
    """

    ALLOWED_TRANSITIONS: dict[GameState, set[GameState]] = {
        GameState.LOBBY: {GameState.GENERATING},
        GameState.GENERATING: {GameState.READY, GameState.FINISHED},
        GameState.READY: {GameState.IN_PROGRESS},
        GameState.IN_PROGRESS: {GameState.FINISHED},
        GameState.FINISHED: set(),
    }

    def transition(self, current: GameState, target: GameState) -> GameState:
        if target not in self.ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransition(
                f"Cannot transition from {current} → {target}"
            )

        return target