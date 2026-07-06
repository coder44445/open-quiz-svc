from app.domain.question.difficutly import Difficulty
import json
from ollama import AsyncClient

from app.domain.question.model import Question


class OllamaProvider:

    def __init__(self, model: str):
        self.client = AsyncClient()
        self.model = model

    async def generate_questions(self, topics: list[str], difficulty: Difficulty, count: int):
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

        response = await self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )

        if not isinstance(response, dict):
            raise ValueError('Unexpected response from Ollama provider')

        content = response.get('message', {}).get('content')
        if not isinstance(content, str):
            raise ValueError('Ollama response content is missing or invalid')

        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError('Ollama provider must return a list of questions')

        return data
