from typing import Any, Optional

from pydantic import BaseModel, Field


class EmitLogResult(BaseModel):
    """Outcome of an ``emit_log`` call. ``ok=False`` on failure; never raises."""

    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    sending_stopped: bool = Field(
        default=False,
        description="True when the SDK did not send this line to the platform because sending is "
        "stopped for this run (cap reached or the platform refused an earlier one). It is still logged locally.",
    )
