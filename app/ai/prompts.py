import random
from app.domain.question.difficutly import Difficulty


# Optimal True/False question counts per batch size.
# Targets roughly 20% TF while keeping at least 1 TF per meaningful batch.
# Key: batch_size  Value: number of TF questions to include
_TF_COUNT_TABLE: dict[int, int] = {
    1: 0,   # resolved dynamically via random roll
    2: 0,   # resolved dynamically via random roll (50% chance)
    3: 1,
    4: 1,
    5: 1,
    6: 1,
    7: 1,
    8: 2,
    9: 2,
    10: 2,
    11: 2,
    12: 2,
    13: 3,
    14: 3,
    15: 3,
    16: 3,
    17: 3,
    18: 4,
    19: 4,
    20: 4,
}


class PromptBuilder:

    @staticmethod
    def quiz_prompt(
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> str:
        topics = topics or ["general knowledge"]
        topics_list_str = ", ".join([f'"{t}"' for t in topics])

        # ── Determine format rules based on batch count ──────────────────
        if count == 1:
            # 20% chance of True/False for a single-question batch
            if random.random() < 0.20:
                format_rules = (
                    "- This question MUST be a True/False question.\n"
                    '                - The options array MUST be exactly ["True", "False"] '
                    "and correct_index must be 0 or 1."
                )
            else:
                format_rules = (
                    "- This question MUST be a multiple choice question with exactly 4 options.\n"
                    "                - Do NOT generate a True/False question."
                )
        elif count == 2:
            # 50% chance of one TF in a two-question batch
            if random.random() < 0.50:
                format_rules = (
                    "- Exactly 1 of the 2 questions MUST be a True/False question.\n"
                    "                - The other question MUST be multiple choice with exactly 4 options.\n"
                    '                - For the True/False question the options array MUST be exactly ["True", "False"] '
                    "and correct_index must be 0 or 1."
                )
            else:
                format_rules = (
                    "- Both questions MUST be multiple choice questions with exactly 4 options.\n"
                    "                - Do NOT generate any True/False questions."
                )
        else:
            # Look up the exact TF count for this batch size (default to ~20%)
            tf_count = _TF_COUNT_TABLE.get(count, max(1, round(count * 0.20)))
            mcq_count = count - tf_count
            format_rules = (
                f"- Exactly {tf_count} question(s) out of {count} MUST be True/False questions.\n"
                f"                - The remaining {mcq_count} question(s) MUST be multiple choice with exactly 4 options.\n"
                '                - For True/False questions the options array MUST be exactly ["True", "False"] '
                "and correct_index must be 0 or 1.\n"
                '                - For multiple choice questions the options array MUST contain exactly 4 strings.'
            )

        return f"""You are an expert quiz question generator. Your only job is to return valid JSON.

                TASK: Generate exactly {count} quiz question(s).
                
                OUTPUT FORMAT:
                - Return ONLY a valid JSON array. No markdown, no explanation, no extra text.
                - The array MUST contain exactly {count} object(s). Not more, not less.
                - Each object MUST have exactly these 5 fields:
                  1. "question" (string) — the question text
                  2. "options"  (array of strings) — the answer choices
                  3. "correct_index" (integer) — the 0-based index of the correct option in "options"
                  4. "topic" (string) — MUST exactly match one of: {topics_list_str}
                  5. "difficulty" (string) — MUST equal "{difficulty.value}"
                
                QUESTION RULES:
                - {format_rules}
                - Exactly ONE correct answer per question. correct_index must point to the right answer.
                - Distribute questions evenly across topics: {topics_list_str}.
                - Questions must be factually accurate, unambiguous, and appropriate for the difficulty.
                - Do NOT repeat similar questions.
                
                CRITICAL: Return ONLY the JSON array. Any text outside the JSON will break the parser.
            """