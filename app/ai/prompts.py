from app.domain.question.difficutly import Difficulty




class PromptBuilder:

    @staticmethod
    def quiz_prompt(
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> str:
        topic_str = topics[0] if topics else "general knowledge"
        return f"""You are an expert MCQ generator.

                Generate exactly {count} multiple-choice questions.

                Return ONLY valid JSON.

                Requirements:
                - The top-level JSON value MUST be an array.
                - The array MUST contain exactly {count} objects.
                - NEVER return a single JSON object.
                - NEVER include markdown, explanations, reasoning, or any text outside the JSON.
                - Each object must contain exactly these fields:
                - question (string)
                - options (array of strings)
                - correct_index (integer matching the correct option's index)
                - topic (string)
                - difficulty (string)

                Rules:
                - Exactly one correct answer.
                - Most questions should be multiple choice with exactly 4 options.
                - About 15% to 25% of the questions should be True/False questions.
                - For True/False questions, the options array MUST be exactly ["True", "False"] and correct_index must be 0 or 1.
                - topic must equal "{topic_str}".
                - difficulty must equal "{difficulty.value}".
                
                Do not return a single object under any circumstance.
            """