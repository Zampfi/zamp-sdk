from typing import Optional

from pydantic import BaseModel


class InputOption(BaseModel):
    """One selectable option for a ``select_one`` / ``multiple_choice`` question."""

    id: str
    label: str
    description: Optional[str] = None
