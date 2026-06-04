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
    """The user's answer to a prior ``request_user_input``, recovered on re-run.

    Built from the JSON the platform appends to the resume command, whose shape
    is ``{"responses": [{"response": {...}, "file_references": [...]}, ...]}`` —
    one entry per question asked in the originating call (same order).
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
        if index >= len(self.responses):
            return []
        item = self.responses[index] or {}
        return item.get("file_references") or []

    def file_paths_for(self, index: int = 0) -> list[str]:
        """Absolute, ready-to-open sandbox paths for files attached to the
        *index*-th question.

        Prefer this over ``files_for`` when you just want to open the files:
        it resolves the home-relative paths the platform returns
        (``"<user>/uploads/.../f.pdf"``) to absolute ones
        (``"/home/<user>/uploads/.../f.pdf"``). Entries without a path are skipped.
        """
        return [_resolve_sandbox_path(p) for f in self.files_for(index) if (p := (f or {}).get("path"))]

    def _response(self, index: int) -> Optional[dict]:
        if index >= len(self.responses):
            return None
        item = self.responses[index] or {}
        return item.get("response") or item
