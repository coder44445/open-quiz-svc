from app.domain.question.difficutly import Difficulty




class PromptBuilder:

    @staticmethod
    def quiz_prompt(
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> str:
        ...