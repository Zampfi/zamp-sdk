from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel

from zamp_sdk.logging.constants import EMIT_ID_PREFIX


def new_emit_id() -> str:
    """Generate a unique, prefixed identifier for a script-emitted tool-call block."""
    return f"{EMIT_ID_PREFIX}{uuid.uuid4().hex}"


def stringify_tool_result(value: Any) -> str:
    """Normalize a tool result to the string form the platform expects.

    Pretty-prints dicts, lists, and Pydantic models as indented JSON. Strings
    pass through unchanged. ``None`` becomes a friendly success marker.
    """
    if value is None:
        return "Success (no output)"
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(), indent=2, default=str)
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, default=str)
    return str(value)
