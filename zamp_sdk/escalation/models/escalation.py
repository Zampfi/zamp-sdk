from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from zamp_sdk.escalation.constants import (
    MAX_CONTEXT_BYTES,
    MAX_QUESTIONS,
    OPTION_INPUT_TYPES,
    QUESTION_INPUT_TYPES,
)


class EscalationRequest(BaseModel):
    """What :func:`escalate` hands over: the questions, what the code saw, and what runs next."""

    model_config = ConfigDict(extra="forbid")

    questions: list[dict] = Field(..., min_length=1, max_length=MAX_QUESTIONS)
    context: Optional[str] = None
    post_action: Optional[dict] = None

    @field_validator("context")
    @classmethod
    def _context_fits(cls, context: Optional[str]) -> Optional[str]:
        if context is not None and len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise ValueError(
                f"context is over {MAX_CONTEXT_BYTES} bytes; save longer material to a file and put its path in context"
            )
        return context

    @field_validator("questions")
    @classmethod
    def _questions_askable(cls, questions: list[dict]) -> list[dict]:
        for i, q in enumerate(questions):
            if q.get("input_type") not in QUESTION_INPUT_TYPES:
                raise ValueError(f"questions[{i}]: input_type must be one of {', '.join(QUESTION_INPUT_TYPES)}")
            if not isinstance(q.get("question"), str) or not q["question"].strip():
                raise ValueError(f"questions[{i}]: question must be a non-empty string")
            if q["input_type"] in OPTION_INPUT_TYPES and not q.get("options"):
                raise ValueError(f"questions[{i}]: a {q['input_type']} question needs options")
            if not isinstance(q.get("requires_human", False), bool):
                raise ValueError(f"questions[{i}]: requires_human must be true or false")
        return questions
