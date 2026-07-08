from __future__ import annotations

import json
import time

import structlog
from ollama import AsyncClient

from app.domain.question.difficutly import Difficulty
from app.domain.question.model import Question
from app.core.config import settings

logger = structlog.get_logger(__name__)


class OllamaProvider:
    """AI question-generation provider backed by a local Ollama instance.

    Sends a single-shot prompt to the configured Ollama model and expects a
    JSON array of question objects in return.  All connection parameters
    (host, model, temperature, timeout) are read from application settings
    so they can be overridden via environment variables without code changes.
    """

    def __init__(self, model: str) -> None:
        # Use the host from settings; AsyncClient defaults to localhost:11434
        # but we honour OLLAMA_HOST for Docker / remote deployments.
        self.client = AsyncClient(host=settings.ollama_host)
        self.model = model

    async def generate_questions(
        self,
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> list[dict]:
        """Call the Ollama chat API and return raw question dicts.

        Args:
            topics:     Topics to include in the prompt.
            difficulty: Difficulty level string forwarded to the model.
            count:      Number of questions requested.

        Returns:
            List of raw question dicts (not yet validated as domain objects).

        Raises:
            ValueError: If the response structure or JSON content is unexpected.
        """

        log = logger.bind(model=self.model, topics=topics, count=count, difficulty=difficulty.value)
        log.info("ollama_request_started")

        prompt = f"""
                Generate {count} MCQ questions.

                Topics: {topics}
                Difficulty: {difficulty}

                Return ONLY valid JSON:
                [
                  {{
                    "question": "...",
                    "options": ["a","b","c","d"],
                    "correct_index": 0,
                    "topic": "...",
                    "difficulty": "{difficulty}"
                  }}
                ]
            """

        start = time.perf_counter()

        try:
            response = await self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": settings.llm_temperature,
                },
            )
        except Exception:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            log.exception("ollama_request_failed", elapsed_ms=elapsed_ms)
            raise

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info("ollama_response_received", elapsed_ms=elapsed_ms)

        # Ollama returns a chat completion object; extract the assistant message.
        if not isinstance(response, dict):
            log.error(
                "ollama_unexpected_response_type",
                actual_type=type(response).__name__,
            )
            raise ValueError("Unexpected response from Ollama provider")

        content = response.get("message", {}).get("content")
        if not isinstance(content, str):
            log.error(
                "ollama_missing_content",
                message_keys=list(response.get("message", {}).keys()),
            )
            raise ValueError("Ollama response content is missing or invalid")

        # Parse the JSON array out of the model's text response.
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            log.error(
                "ollama_json_parse_failed",
                error=str(exc),
                # Log first 200 chars to help debug malformed responses.
                content_preview=content[:200],
            )
            raise ValueError(f"Ollama returned invalid JSON: {exc}") from exc

        if not isinstance(data, list):
            log.error(
                "ollama_response_not_a_list",
                actual_type=type(data).__name__,
            )
            raise ValueError("Ollama provider must return a list of questions")

        log.info("ollama_parsed_questions", raw_count=len(data))
        return data
