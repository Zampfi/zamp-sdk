from typing import Any, Optional

from pydantic import BaseModel


class EmitLogResult(BaseModel):
    """Outcome of an ``emit_log`` call. ``ok=False`` on failure; never raises."""

    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None
