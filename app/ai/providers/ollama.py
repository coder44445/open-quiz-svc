from __future__ import annotations

import json
import time

import structlog
from ollama import AsyncClient

from app.domain.question.difficutly import Difficulty
from app.core.config import settings
from app.ai.prompts import PromptBuilder

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

        prompt = PromptBuilder.quiz_prompt(topics, difficulty, count)

        start = time.perf_counter()

        try:
            response = await self.client.chat(
                model=self.model,
                think=False,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={
                    "temperature": settings.llm_temperature,
                },
            )
        except Exception:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            log.exception("ollama_request_failed", elapsed_ms=elapsed_ms)
            raise

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info("ollama_response_received", elapsed_ms=elapsed_ms,response=response)

        # Ollama returns a ChatResponse object (often a Pydantic model or dataclass in newer versions)
        try:
            content = response.message.content
        except AttributeError:
            # Fallback if it's somehow a dict in an older version
            content = getattr(response, "get", lambda x, y: {})("message", {}).get("content")

        if not isinstance(content, str):
            log.error(
                "ollama_missing_content",
                actual_type=type(response).__name__,
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

    async def verify_question(self, question_text: str, options: list[str]) -> int | None:
        """Ask the model to answer a question from the generated set as a verifier.

        Generating a question and answering it are different cognitive tasks —
        even small models answer multiple-choice more reliably than they generate
        correct answers from scratch. Using the model as its own verifier catches
        the most common failure: a wrong correct_index.

        Returns the 0-based index the model chose, or None if the response
        cannot be parsed (treated as a non-fatal inconclusive result).
        """
        options_text = "\n".join(f"{i}. {opt}" for i, opt in enumerate(options))
        prompt = (
            f"Question: {question_text}\n\n"
            f"Options:\n{options_text}\n\n"
            "Which option index (0, 1, 2, or 3) is correct? "
            "Reply with ONLY the digit — no explanation."
        )

        log = logger.bind(model=self.model)
        try:
            response = await self.client.chat(
                model=self.model,
                think=False,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0},
            )
            content = (response.message.content or "").strip()
            # Accept first digit found in response — model sometimes adds punctuation
            for ch in content:
                if ch.isdigit():
                    idx = int(ch)
                    if 0 <= idx < len(options):
                        return idx
            log.warning("verify_question_unparseable", content_preview=content[:50])
            return None
        except Exception:
            log.warning("verify_question_failed")
            return None
