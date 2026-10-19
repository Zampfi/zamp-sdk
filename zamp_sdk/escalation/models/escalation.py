from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from zamp_sdk.escalation.constants import (
    MAX_DETAILS_BYTES,
    MAX_FILES,
    MAX_QUESTIONS,
    MAX_SUMMARY_CHARS,
    OPTION_INPUT_TYPES,
    QUESTION_INPUT_TYPES,
)
from zamp_sdk.user_input.models import UserInputResponse


class EscalationFile(BaseModel):
    """A file the code points the agent (and, when asked, the user) at: an absolute sandbox path."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    name: Optional[str] = None


class EscalationRequest(BaseModel):
    """What :func:`escalate` hands over: the blocker, what the code saw, and what it needs back."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1, max_length=MAX_SUMMARY_CHARS)
    details: Optional[str] = None
    files: list[EscalationFile] = Field(default_factory=list, max_length=MAX_FILES)
    questions: list[dict] = Field(..., min_length=1, max_length=MAX_QUESTIONS)
    answer_schema: Optional[dict] = None
    requires_human: bool = False
    post_action: Optional[dict] = None

    @field_validator("details")
    @classmethod
    def _details_fit(cls, details: Optional[str]) -> Optional[str]:
        if details is not None and len(details.encode("utf-8")) > MAX_DETAILS_BYTES:
            raise ValueError(f"details is over {MAX_DETAILS_BYTES} bytes; put longer material in a file")
        return details

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


class EscalationAnswer(UserInputResponse):
    """The answers to a prior :func:`escalate`, recovered by the next run.

    One response per question asked, in the same order, so the :class:`UserInputResponse`
    accessors (``selected_option_for``, ``text_for``, ``files_for``) read them as they read a
    human's answer. An answer the agent or a parent task gave is already in the question's own
    shape: a typed reply to an options question comes back as the option it meant, with the
    person's words in :meth:`human_text_for`.
    """

    escalation_id: Optional[str] = None
    note: Optional[str] = None
    value: Any = None

    def answered_by_for(self, index: int = 0) -> Optional[str]:
        """Who answered the *index*-th question: ``"agent"``, ``"human"`` or ``"parent_agent"``."""
        return self._entry(index).get("answered_by")

    def human_text_for(self, index: int = 0) -> Optional[str]:
        """What a person typed for the *index*-th question, when the answer came from their words."""
        return self._entry(index).get("human_text")

    def _entry(self, index: int) -> dict:
        if index >= len(self.responses):
            return {}
        return self.responses[index] or {}
