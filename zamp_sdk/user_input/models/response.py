from typing import Optional

from pydantic import BaseModel, Field


class UserInputResponse(BaseModel):
    """The user's answer to a prior ``request_user_input``, recovered on re-run."""

    responses: list[dict] = Field(default_factory=list)

    def selected_option_for(self, index: int = 0) -> Optional[str]:
        """The selected option id for the *index*-th question (select_one)."""
        resp = self._response(index)
        return (resp or {}).get("selected_option")

    def text_for(self, index: int = 0) -> Optional[str]:
        """The free-text / custom answer for the *index*-th question."""
        resp = self._response(index)
        if not resp:
            return None
        return resp.get("custom_input") or resp.get("text")

    def _response(self, index: int) -> Optional[dict]:
        if index >= len(self.responses):
            return None
        item = self.responses[index] or {}
        return item.get("response") or item
