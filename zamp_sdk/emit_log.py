"""Stream a content block back to the Zamp platform so it becomes visible in
the agent's live message in real time.

Emit one block per call. For a tool-call log emit the ``tool_use`` first,
do the work, then emit the matching ``tool_result`` sharing the same ``id``.

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

import json
import os
import uuid
from typing import Any, Optional

import structlog
from pydantic import BaseModel

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.content_blocks import (
    ContentBlock,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
)

logger = structlog.get_logger(__name__)

EMIT_LOG_ACTION_NAME = "emit_log"

ENV_CHANNEL_TYPE = "ZAMP_CHANNEL_TYPE"
ENV_CHANNEL_ID = "ZAMP_CHANNEL_ID"
ENV_STREAMING_ID = "ZAMP_STREAMING_ID"
ENV_MESSAGE_ID = "ZAMP_MESSAGE_ID"
ENV_TOOL_CALL_ID = "ZAMP_TOOL_CALL_ID"
ENV_RUN_ID = "ZAMP_RUN_ID"

EMIT_ID_PREFIX = "emit_"


def _new_emit_id() -> str:
    """Mint a fresh prefixed block id for a script-emitted tool call."""
    return f"{EMIT_ID_PREFIX}{uuid.uuid4().hex}"


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
    # Auto-stamp parent_block_id from the running tool's id so emitted blocks
    # group under the correct parent when parallel tool calls interleave.
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


async def emit_text(content: str) -> EmitLogResult:
    """Emit a progress/milestone text log into the running agent message.

    Thin wrapper around :func:`emit_log` for the most common case. Returns the
    same :class:`EmitLogResult`; never raises.
    """
    logger.info("emit_text", content=content)
    return await emit_log(TextContentBlock(content=content))


async def emit_tool_use(
    name: str,
    *,
    display_title: Optional[str] = None,
    input: Optional[dict] = None,
    id: Optional[str] = None,
) -> str:
    """Emit a ``tool_use`` log block (mirrors an action call as "running").

    Pair with :func:`emit_tool_result` using the returned id. Use this whenever
    your script is about to do work the user should see in the live message.

    Args:
        name: Tool/action name (e.g. ``"GOOGLE_CALENDAR_LIST_EVENTS"``).
        display_title: Short human-readable summary shown as the block header
            (e.g. ``"Fetching events Mon → Sun"``). Optional.
        input: Tool input as a plain Python dict — the helper JSON-encodes it.
            Optional.
        id: Override the auto-minted id. Leave unset to get a fresh
            ``emit_<hex>`` id back.

    Returns:
        The block ``id``. Pass it to :func:`emit_tool_result` to complete the
        pair. Returned even on emit failure, so the caller can still pair the
        result; the failure is logged but not raised.
    """
    tool_id = id or _new_emit_id()
    input_json = json.dumps(input) if input is not None else None
    logger.info(
        "emit_tool_use",
        id=tool_id,
        name=name,
        display_title=display_title,
        input_json=input_json,
    )
    await emit_log(
        ToolUseContentBlock(
            id=tool_id,
            name=name,
            display_title=display_title,
            input_json=input_json,
        )
    )
    return tool_id


def _stringify_tool_result(value: Any) -> str:
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


async def emit_tool_result(
    id: str,
    content: Any,
    *,
    name: Optional[str] = None,
) -> EmitLogResult:
    """Emit a ``tool_result`` log block paired with a prior :func:`emit_tool_use`.

    Args:
        id: The id returned by :func:`emit_tool_use` — same string pairs the
            two blocks.
        content: Result to show under the tool block. Pass the raw value you
            got back from your action call — dicts and Pydantic models are
            auto-pretty-printed as JSON; strings pass through unchanged.
        name: Optional tool name (recommended for consistent rendering).
    """
    stringified = _stringify_tool_result(content)
    logger.info("emit_tool_result", id=id, name=name, content=stringified)
    return await emit_log(ToolResultContentBlock(id=id, name=name, content=stringified))
