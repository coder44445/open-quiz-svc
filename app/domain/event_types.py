class EventType:
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    TOPIC_ADDED = "topic_added"

    # Topic collection: server requests topics from randomly selected players.
    TOPIC_REQUEST = "topic_request"
    TOPICS_COLLECTED = "topics_collected"

    JOB_STARTED = "job_started"
    JOB_PROGRESS = "job_progress"
    # Fired after each individual question is generated and persisted.
    QUESTION_READY = "question_ready"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"

    GAME_STATE_CHANGED = "game_state_changed"
    SESSION_SYNC = "session_sync"

    # Broadcasted by game loop — carries the full question for all players.
    QUESTION_SENT = "question_sent"
    # Broadcasted after time limit / all answered — reveals correct answer + leaderboard.
    QUESTION_RESULT = "question_result"

    ANSWER_RECEIVED = "answer_received"
    GAME_FINISHED = "game_finished"
    CHAT_MESSAGE = "chat_message"
    TIMER_ADJUSTED = "timer_adjusted"
    PLAYER_KICKED = "player_kicked"
    GAME_CONFIGURED = "game_configured"