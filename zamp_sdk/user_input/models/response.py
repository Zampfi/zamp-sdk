import os
from typing import Optional

from pydantic import BaseModel, Field


def _resolve_sandbox_path(path: str) -> str:
    """Resolve a file-reference path to an absolute, openable sandbox path.

    Uploaded-file references come back **relative to the sandbox home root**
    (e.g. ``"idem_e68a7c/uploads/<id>/report.pdf"``); the real file lives at
    ``"/home/idem_e68a7c/uploads/<id>/report.pdf"``. ``~``-paths and
    already-absolute paths are returned unchanged.
    """
    if path.startswith("~"):
        return os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return "/home/" + path.lstrip("/")


class UserInputResponse(BaseModel):
    """The answers to a prior ``request_user_input`` or ``escalate``, recovered by the next run.

    Built from the JSON the platform hands that run, whose shape is
    ``{"responses": [{"response": {...}, "file_references": [...]}, ...]}`` —
    one entry per question asked in the originating call (same order). An
    escalation's entries also say who answered, and what a person typed.
    """

    responses: list[dict] = Field(default_factory=list)

    def selected_option_for(self, index: int = 0) -> Optional[str]:
        """The selected option id for the *index*-th question (select_one)."""
        resp = self._response(index)
        return (resp or {}).get("selected_option")

    def selected_options_for(self, index: int = 0) -> list[str]:
        """The selected option ids for the *index*-th question (multiple_choice)."""
        resp = self._response(index)
        return (resp or {}).get("selected_options") or []

    def text_for(self, index: int = 0) -> Optional[str]:
        """The free-text / custom answer for the *index*-th question."""
        resp = self._response(index)
        if not resp:
            return None
        return resp.get("custom_input") or resp.get("text")

    def files_for(self, index: int = 0) -> list[dict]:
        """Files the user attached to the *index*-th question.

        Each entry is ``{"path": ..., "name": ...}`` where ``path`` points at the
        uploaded file in the sandbox filesystem (``~``-relative or absolute) — open
        it directly; the bytes are already staged in the sandbox, only the path
        travels on the command line.
        """
        return self._entry(index).get("file_references") or []

    def file_paths_for(self, index: int = 0) -> list[str]:
        """Absolute, ready-to-open sandbox paths for files attached to the
        *index*-th question.

        Prefer this over ``files_for`` when you just want to open the files:
        it resolves the home-relative paths the platform returns
        (``"<user>/uploads/.../f.pdf"``) to absolute ones
        (``"/home/<user>/uploads/.../f.pdf"``). Entries without a path are skipped.
        """
        return [_resolve_sandbox_path(p) for f in self.files_for(index) if (p := (f or {}).get("path"))]

    def answered_by_for(self, index: int = 0) -> Optional[str]:
        """Who answered the *index*-th question of an escalation: ``"agent"``, ``"human"`` or
        ``"parent_agent"``. ``None`` when the entry does not say, as for a
        ``request_user_input`` answer, which only a person gives."""
        return self._entry(index).get("answered_by")

    def human_text_for(self, index: int = 0) -> Optional[str]:
        """What a person typed for the *index*-th question of an escalation, when its answer
        was made from their words (text against an options question comes back as the option
        they meant); ``None`` otherwise."""
        return self._entry(index).get("human_text")

    def _entry(self, index: int) -> dict:
        if index >= len(self.responses):
            return {}
        return self.responses[index] or {}

    def _response(self, index: int) -> dict:
        item = self._entry(index)
        return item.get("response") or item
