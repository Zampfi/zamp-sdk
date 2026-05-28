"""Stream a content block from a sandboxed script back to the Zamp platform so
it becomes visible in the agent's live message in real time.

``emit_log`` accepts the same :data:`ContentBlock` shape the platform uses
everywhere else — no special "log block" type. Emit one block per call; for a
tool-call log emit the ``tool_use`` first (the FE will show it running), do
the work, then emit the matching ``tool_result`` (sharing the same ``id``).

Example — text progress::

    from zamp_sdk import emit_log, TextContentBlock

    await emit_log(TextContentBlock(content="Fetched 30/120 events"))

Example — a tool-call log (use first, work, result later)::

    import json, uuid
    from zamp_sdk import emit_log, ToolUseContentBlock, ToolResultContentBlock

    tcid = str(uuid.uuid4())
    await emit_log(ToolUseContentBlock(
        id=tcid,
        name="GOOGLE_CALENDAR_LIST_EVENTS",
        display_title="Fetching calendar events (last 60 days)",
        input_json=json.dumps({"time_min": ..., "time_max": ...}),
    ))
    # ... do the actual work ...
    await emit_log(ToolResultContentBlock(
        id=tcid, name="GOOGLE_CALENDAR_LIST_EVENTS",
        content="Fetched 87 events",
    ))
"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog
from pydantic import BaseModel

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.content_blocks import ContentBlock

logger = structlog.get_logger(__name__)

EMIT_LOG_ACTION_NAME = "emit_log"

ENV_CHANNEL_TYPE = "ZAMP_CHANNEL_TYPE"
ENV_CHANNEL_ID = "ZAMP_CHANNEL_ID"
ENV_STREAMING_ID = "ZAMP_STREAMING_ID"
ENV_MESSAGE_ID = "ZAMP_MESSAGE_ID"
ENV_TOOL_CALL_ID = "ZAMP_TOOL_CALL_ID"
ENV_RUN_ID = "ZAMP_RUN_ID"


class EmitLogResult(BaseModel):
    """Outcome of an :func:`emit_log` call. ``ok=False`` on failure; never raises."""

    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None


def _resolve_context() -> dict[str, Any]:
    context = {
        "channel_type": os.environ.get(ENV_CHANNEL_TYPE),
        "channel_id": os.environ.get(ENV_CHANNEL_ID),
        "streaming_id": os.environ.get(ENV_STREAMING_ID),
        "message_id": os.environ.get(ENV_MESSAGE_ID),
        "tool_call_id": os.environ.get(ENV_TOOL_CALL_ID),
        "run_id": os.environ.get(ENV_RUN_ID),
    }
    return {k: v for k, v in context.items() if v}


async def emit_log(block: ContentBlock) -> EmitLogResult:
    """Emit a content block to the current agent context.

    Args:
        block: A :data:`ContentBlock` to append. For a tool-call log emit the
            ``tool_use`` first, do the work, then emit the matching
            ``tool_result`` sharing the same ``id``.

    Returns:
        :class:`EmitLogResult`. Never raises.
    """
    # Auto-stamp parent_block_id from the running tool's id so the FE attributes
    # this block to the correct parent even when parallel tool calls interleave.
    # Caller can override by setting it explicitly on the block.
    if block.parent_block_id is None:
        block.parent_block_id = os.environ.get(ENV_TOOL_CALL_ID)

    params: dict[str, Any] = {
        "block": block.model_dump(mode="json"),
        "context": _resolve_context(),
    }

    try:
        result = await ActionExecutor.execute(
            EMIT_LOG_ACTION_NAME,
            params,
            summary="Emit log to current agent context",
        )
        return EmitLogResult(ok=True, result=result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit_log failed", error=str(exc))
        return EmitLogResult(ok=False, error=str(exc))
