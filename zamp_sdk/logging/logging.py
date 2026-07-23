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

from pydantic import ValidationError

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.capture import capture_active, capture_step, suppress_step_capture
from zamp_sdk.context import (
    ENV_INSIDE_SANDBOX,
    ENV_TOOL_CALL_ID,
    ChannelContext,
    current_channel_context,
    resolve_context,
)
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


def _clean_block_entry(block: ContentBlock) -> dict[str, Any]:
    """A compact, logger-style capture entry for an emitted block — the same shape
    as the ``emit_*`` structured logs, not the full serialized block."""
    if isinstance(block, TextContentBlock):
        return {"event": "emit_text", "content": block.content}
    if isinstance(block, ToolUseContentBlock):
        return {
            "event": "emit_tool_use",
            "id": block.id,
            "name": block.name,
            "display_title": block.display_title,
            "input_json": block.input_json,
        }
    if isinstance(block, ToolResultContentBlock):
        return {
            "event": "emit_tool_result",
            "id": block.id,
            "name": block.name,
            "content": block.content,
        }
    return {"event": "emit_log", **block.model_dump(mode="json")}


def _inside_sandbox() -> bool:
    return os.environ.get(ENV_INSIDE_SANDBOX) == "true"


def _emit_context() -> dict[str, Any]:
    """Resolve the agent context to attach to an emitted block.

    Inside a sandbox the runtime injects the context as ``ZAMP_*`` env vars.
    Otherwise (the code-executor case) it comes from the context the running
    workflow bound via :func:`zamp_sdk.bind_channel_context`. Returns a flat dict
    that is wire-compatible with the platform's ``EmitLogContext`` either way.
    """
    if _inside_sandbox():
        return resolve_context()
    ctx = current_channel_context()
    return ctx.model_dump(exclude_none=True) if ctx else {}


def _emit_channel_context() -> Optional[dict[str, Any]]:
    """The full channel context to also send as ``channel_context`` — the field platform
    actions are migrating to. Returns a validated ``ChannelContext`` (as a dict) when a
    complete, valid one is available (UUID channel_id, conversation/task channel_type),
    else None so the receiver falls back to ``context``."""
    ctx: Optional[ChannelContext]
    if _inside_sandbox():
        try:
            ctx = ChannelContext(**resolve_context())
        except ValidationError:
            return None
    else:
        ctx = current_channel_context()
    return ctx.model_dump(mode="json") if ctx is not None else None


def _current_tool_call_id() -> Optional[str]:
    """The running tool's id, from env in a sandbox or the bound context."""
    if _inside_sandbox():
        return os.environ.get(ENV_TOOL_CALL_ID)
    ctx = current_channel_context()
    return ctx.tool_call_id if ctx else None


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
        block.parent_block_id = _current_tool_call_id()

    block_payload = block.model_dump(mode="json")

    if capture_active():
        capture_step(_clean_block_entry(block))

    params: dict[str, Any] = {
        "block": block_payload,
        "context": _emit_context(),
    }
    # Also send the full context as `channel_context` (the field consumers are migrating
    # to). Only when a complete, valid one is available; otherwise consumers use `context`.
    channel_context = _emit_channel_context()
    if channel_context is not None:
        params["channel_context"] = channel_context

    try:
        # The block is already captured above; suppress capture of this action call so
        # emit_log isn't recorded twice.
        with suppress_step_capture():
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
