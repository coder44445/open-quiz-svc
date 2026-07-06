import time
from app.domain.game.session import GameSession
from app.domain.player.model import Player
from app.domain.question.model import Question
from app.domain.game.answer import Answer
from app.domain.game.state import GameState


def test_game_session_basic_flow():
    s = GameSession(room_id="r1")
    p = Player(name="alice")
    s.add_player(p)
    assert p.id in s.players

    s.add_topic("math")
    s.add_topic("science")
    # simulate a realistic state progression for play
    s.set_state(GameState.GENERATING)
    s.set_state(GameState.READY)
    s.questions = [
        Question(id=0, topic="math", text="q1", options=["a", "b"], correct_index=0)
    ]
    s.set_state(GameState.IN_PROGRESS)
    assert s.state == GameState.IN_PROGRESS
    assert len(s.questions) == 1

    q = s.get_current_question()
    assert isinstance(q, Question)

    # submit an answer accepted
    ans = Answer(player_id=p.id, question_id=q.id, selected_index=0, time_taken=0.5)
    accepted = s.submit_answer(ans)
    assert accepted is True

    # duplicate answer rejected
    accepted2 = s.submit_answer(ans)
    assert accepted2 is False

    # move to next question
    current_index = s.current_question_index
    s.next_question()
    assert s.current_question_index == current_index + 1
