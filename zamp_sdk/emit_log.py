"""Stream content blocks from a sandboxed script back to the Zamp platform so
they become visible in the agent's live message in real time.

``emit_log`` accepts the same :data:`ContentBlock` shape the platform uses
everywhere else — no special "log block" type.

Example — markdown progress::

    from zamp_sdk import emit_log, MarkdownContentBlock

    await emit_log([MarkdownContentBlock(content="**Progress** — fetched 30/120")])

Example — a tool-call log (paired ``tool_use`` + ``tool_result`` sharing one id)::

    import json, uuid
    from zamp_sdk import emit_log, ToolUseContentBlock, ToolResultContentBlock

    tcid = str(uuid.uuid4())
    await emit_log([
        ToolUseContentBlock(
            id=tcid,
            name="GOOGLE_CALENDAR_LIST_EVENTS",
            display_title="Fetching calendar events (last 60 days)",
            input_json=json.dumps({"time_min": ..., "time_max": ...}),
        ),
        ToolResultContentBlock(
            id=tcid, name="GOOGLE_CALENDAR_LIST_EVENTS",
            content="Fetched 87 events",
        ),
    ])
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

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


async def emit_log(blocks: List[ContentBlock]) -> EmitLogResult:
    """Emit one or more content blocks to the current agent context.

    Args:
        blocks: List of :data:`ContentBlock` to append in order. A paired
            ``tool_use`` + ``tool_result`` must share an ``id`` and be passed
            together so they land contiguously.

    Returns:
        :class:`EmitLogResult`. Never raises.
    """
    if not blocks:
        return EmitLogResult(ok=False, error="emit_log: blocks list is empty")

    params: dict[str, Any] = {
        "blocks": [b.model_dump(mode="json") for b in blocks],
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
