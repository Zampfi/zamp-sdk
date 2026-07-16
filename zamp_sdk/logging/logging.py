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
from typing import Any, Optional

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import ENV_TOOL_CALL_ID, resolve_context
from zamp_sdk.logger import get_logger
from zamp_sdk.logging.constants import EMIT_LOG_ACTION_NAME
from zamp_sdk.logging.models import (
    ContentBlock,
    EmitLogResult,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
)
from zamp_sdk.logging.utils import new_emit_id, stringify_tool_result

logger = get_logger(__name__)


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
        "context": resolve_context(),
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
    tool_id = id or new_emit_id()
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
    stringified = stringify_tool_result(content)
    logger.info("emit_tool_result", id=id, name=name, content=stringified)
    return await emit_log(ToolResultContentBlock(id=id, name=name, content=stringified))
