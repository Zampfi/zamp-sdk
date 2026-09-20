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

from zamp_sdk.capture import capture_active, capture_step
from zamp_sdk.context import (
    ENV_TOOL_CALL_ID,
    ExecutionHost,
    current_channel_context,
    current_execution_host,
)
from zamp_sdk.logger import get_logger
from zamp_sdk.logging.constants import EMIT_LOG_ACTION_NAME, LogLevel
from zamp_sdk.logging.log_control import should_emit
from zamp_sdk.logging.models import (
    ContentBlock,
    EmitLogResult,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
)
from zamp_sdk.logging.utils import new_emit_id, stringify_tool_result

logger = get_logger(__name__)


async def _emit_text_line(content: str, level: LogLevel) -> EmitLogResult:
    """One of the script's own lines: gate it, record it, send it.

    The three steps live here rather than in :func:`emit_log` so that only the named helpers
    record anything. ``emit_log`` stays the plain escape hatch — it is how a ``tool_use`` /
    ``tool_result`` block is sent, and those must not reach the file: the action they describe
    is already an ``action`` step, and restating it around every call is the duplication that
    made the file unreadable.

    Gating here too, rather than leaving it to ``emit_log``, is what keeps one rule over both
    surfaces: a line the run chose not to show is a line it does not record either. The second
    check inside ``emit_log`` still guards anyone calling it directly, and costs one comparison.
    """
    if not should_emit(level):
        return EmitLogResult(ok=True)
    _capture_text_log(content, level)
    return await emit_log(TextContentBlock(content=content), level=level)


def _capture_text_log(content: str, level: LogLevel) -> None:
    """Record the line in the step buffer, so it survives in the run's log file.

    Called *before* the send, so a line whose delivery then failed is still recorded — the
    moment an author's own error text is most worth having.

    Never raises: this is bookkeeping wrapped around someone's log line.
    """
    if not capture_active():
        return
    try:
        capture_step({"event": "log", "level": str(level), "content": content})
    except Exception as exc:
        logger.warning("could not capture the log line", error=repr(exc))


def _current_tool_call_id() -> Optional[str]:
    """The running tool's id, from whichever source this execution host uses."""
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        ctx = current_channel_context()
        return ctx.tool_call_id if ctx else None
    return os.environ.get(ENV_TOOL_CALL_ID)


async def emit_log(
    block: ContentBlock,
    *,
    level: LogLevel = LogLevel.INFO,
    auto: bool = False,
) -> EmitLogResult:
    """Emit a content block to the current agent context.

    Args:
        block: A :data:`ContentBlock` to append. For a tool-call log emit the
            ``tool_use`` first, do the work, then emit the matching
            ``tool_result`` sharing the same ``id``.
        level: Severity, gated against :func:`configure_logging`'s level. Defaults
            to ``INFO``, which is what every caller before levels existed got.
        auto: Set by the SDK for blocks it emits on your behalf — those have already passed
            their own gate, so the level does not apply to them. Leave it alone.

    Returns:
        :class:`EmitLogResult`. Never raises.
    """
    if not auto and not should_emit(level):
        return EmitLogResult(ok=True)
    try:
        # Auto-stamp parent_block_id from the running tool's id so emitted blocks
        # group under the correct parent when parallel tool calls interleave.
        if block.parent_block_id is None:
            block.parent_block_id = _current_tool_call_id()

        block_payload = block.model_dump(mode="json")

        # No channel context here: the platform stamps it into the params from the
        # verified execution token, and emit_log's input model requires it. A
        # caller-supplied one is not read.
        params: dict[str, Any] = {"block": block_payload}

        # Imported inside the function, not at module top. ``ActionExecutor`` is the one way
        # to run an action and an emit is no exception, so this module depends on it — but it
        # depends on this one back, through the auto-logger. One of the two has to be deferred,
        # and it is this one: by the time an emit happens every module is loaded.
        from zamp_sdk.action_executor import ActionExecutor

        # Nothing special is needed to keep this out of the live message or the step buffer:
        # ``NON_LOGGABLE_ACTIONS`` names it, and both the auto-logger and the step capture
        # check that list.
        result = await ActionExecutor.execute(
            EMIT_LOG_ACTION_NAME,
            params,
            summary="Emit log to current agent context",
        )
        return EmitLogResult(ok=True, result=result)
    except Exception as exc:
        logger.warning("emit_log failed", error=str(exc))
        return EmitLogResult(ok=False, error=str(exc))


async def emit_text(content: str) -> EmitLogResult:
    """Emit a progress/milestone text log into the running agent message.

    Unchanged: an ``INFO`` line, exactly as before levels existed. :func:`emit_info` is the
    same call under the name that says which level it is. Kept as its own function rather
    than an alias so its structured log line still reads ``emit_text``.
    """
    logger.info("emit_text", content=content)
    return await _emit_text_line(content, LogLevel.INFO)


async def emit_info(content: str) -> EmitLogResult:
    """Emit an informational progress line. Shown at the default level."""
    logger.info("emit_info", content=content)
    return await _emit_text_line(content, LogLevel.INFO)


async def emit_debug(content: str) -> EmitLogResult:
    """Emit a diagnostic line, hidden unless the level is lowered to ``DEBUG``.

    The line you can leave in the code permanently: silent by default, there when someone
    turns it on with ``configure_logging(level=LogLevel.DEBUG)``.
    """
    logger.debug("emit_debug", content=content)
    return await _emit_text_line(content, LogLevel.DEBUG)


async def emit_error(content: str) -> EmitLogResult:
    """Emit a failure line. Above every configurable threshold, so it is shown unless
    logging is switched off entirely with ``configure_logging(enabled=False)``."""
    logger.warning("emit_error", content=content)
    return await _emit_text_line(content, LogLevel.ERROR)


async def _emit_tool_use_block(
    name: str,
    *,
    display_title: Optional[str] = None,
    input: Optional[dict] = None,
    id: Optional[str] = None,
    auto: bool = False,
) -> tuple[str, EmitLogResult]:
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
        auto: Reserved for the SDK's own action logging. Leave it alone.

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
    result = await emit_log(
        ToolUseContentBlock(
            id=tool_id,
            name=name,
            display_title=display_title,
            input_json=input_json,
        ),
        auto=auto,
    )
    return tool_id, result


async def emit_tool_use(
    name: str,
    *,
    display_title: Optional[str] = None,
    input: Optional[dict] = None,
    id: Optional[str] = None,
    auto: bool = False,
) -> str:
    """Emit a ``tool_use`` block and return its id. See :func:`_emit_tool_use_block`.

    Always returns the id, even when delivery failed — the caller has an id to pair with either
    way. The SDK's own auto-logger needs to know, so it uses the private form.
    """
    tool_id, _ = await _emit_tool_use_block(name, display_title=display_title, input=input, id=id, auto=auto)
    return tool_id


async def emit_tool_result(
    id: str,
    content: Any,
    *,
    name: Optional[str] = None,
    auto: bool = False,
) -> EmitLogResult:
    """Emit a ``tool_result`` log block paired with a prior :func:`emit_tool_use`.

    Args:
        id: The id returned by :func:`emit_tool_use` — same string pairs the
            two blocks.
        content: Result to show under the tool block. Pass the raw value you
            got back from your action call — dicts and Pydantic models are
            auto-pretty-printed as JSON; strings pass through unchanged.
        name: Optional tool name (recommended for consistent rendering).
        auto: Reserved for the SDK's own action logging. Leave it alone.
    """
    stringified = stringify_tool_result(content)
    logger.info("emit_tool_result", id=id, name=name, content=stringified)
    return await emit_log(ToolResultContentBlock(id=id, name=name, content=stringified), auto=auto)
