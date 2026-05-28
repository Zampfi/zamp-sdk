"""``emit_log`` — stream a log entry from inside a sandboxed script back to the
Zamp platform so it becomes visible to the user in real time.

Anything a long-running ``sandbox_user_exec`` command does is otherwise opaque
until the command finishes. Calling :func:`emit_log` from inside the script
pushes a log entry to the **current** agent context (the conversation or task
the command is running under), or optionally to a **new task** created for the
run.

The entry is a single *log block*. Block kinds are modelled as a discriminated
union (:data:`LogBlock`) — pass the one you want:

- :class:`MarkdownLog` — a markdown line (optional ``title`` / ``level``).
- :class:`ToolCallLog` — renders a proper tool-call block (name + input +
  output), e.g. when a script invokes a tool via the SDK and wants it shown
  like an agent tool call.

Adding a new block kind means adding a union member — never new ``emit_log``
arguments.

Design notes
------------
- **Blocking for now:** the call delegates to :class:`ActionExecutor`, which
  POSTs to ``/actions`` and waits for the platform action to complete. Delivery
  is therefore confirmed and failures surface to the caller. A fire-and-forget
  mode can be added later if per-call latency becomes a problem in hot loops.
- Context (which conversation/task to attach to) is resolved from environment
  variables the platform injects into the sandbox before each
  ``sandbox_user_exec`` call, so callers normally pass only the block.
- The platform-side ``emit_log`` action owns the heavy lifting (building the
  content block, publishing it over SSE, and persisting it). This keeps the SDK
  thin and free of platform-specific content-block shapes.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal, Optional, Union

import structlog
from pydantic import BaseModel, Field

from zamp_sdk.action_executor import ActionExecutor

logger = structlog.get_logger(__name__)

# Action registered on the platform that receives emitted logs.
EMIT_LOG_ACTION_NAME = "emit_log"

# Platform-injected env vars carrying the *current* streaming context. These are
# written into the sandbox by the platform immediately before each
# ``sandbox_user_exec`` call, so a script can emit logs without knowing any ids.
ENV_CHANNEL_TYPE = "ZAMP_CHANNEL_TYPE"  # "conversation" | "task"
ENV_CHANNEL_ID = "ZAMP_CHANNEL_ID"
ENV_STREAMING_ID = "ZAMP_STREAMING_ID"
ENV_MESSAGE_ID = "ZAMP_MESSAGE_ID"
ENV_TOOL_CALL_ID = "ZAMP_TOOL_CALL_ID"
ENV_RUN_ID = "ZAMP_RUN_ID"

LogLevel = Literal["debug", "info", "warning", "error"]
LogTarget = Literal["current", "new_task"]


class MarkdownLog(BaseModel):
    """A markdown log line — the default block kind."""

    type: Literal["markdown"] = "markdown"
    content: str = Field(description="Markdown log content")
    title: Optional[str] = Field(
        default=None, description="Optional short heading to label this entry"
    )
    level: LogLevel = Field(default="info", description="Severity")


class ToolCallLog(BaseModel):
    """A tool-call log block — renders like an agent tool call.

    Use when a script invokes a tool/action and wants it surfaced to the user
    exactly as a direct tool call would appear (name + input + output).
    """

    type: Literal["tool_call"] = "tool_call"
    tool_name: str = Field(description="Tool name")
    tool_input: Optional[dict[str, Any]] = Field(
        default=None, description="Tool input arguments"
    )
    tool_output: Optional[str] = Field(
        default=None, description="Tool result/output content"
    )
    is_error: bool = Field(default=False, description="Mark the tool result as an error")


# Discriminated union of log block kinds. Extend by adding a member, not by
# adding arguments to ``emit_log``.
LogBlock = Annotated[Union[MarkdownLog, ToolCallLog], Field(discriminator="type")]


class EmitLogResult(BaseModel):
    """Outcome of an :func:`emit_log` call.

    ``ok`` is ``False`` when the log could not be sent. The error is also logged;
    it is never raised so the caller's script keeps running.
    """

    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None


def _resolve_context() -> dict[str, Any]:
    """Read the current streaming context from platform-injected env vars."""
    context = {
        "channel_type": os.environ.get(ENV_CHANNEL_TYPE),
        "channel_id": os.environ.get(ENV_CHANNEL_ID),
        "streaming_id": os.environ.get(ENV_STREAMING_ID),
        "message_id": os.environ.get(ENV_MESSAGE_ID),
        "tool_call_id": os.environ.get(ENV_TOOL_CALL_ID),
        "run_id": os.environ.get(ENV_RUN_ID),
    }
    # Drop unset keys so the server sees only what's actually known.
    return {k: v for k, v in context.items() if v}


async def emit_log(
    block: LogBlock,
    *,
    target: LogTarget = "current",
    task_title: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    base_url: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> EmitLogResult:
    """Emit a single log block to the current agent context (or a new task).

    Blocking: waits for the platform action to complete before returning.

    Args:
        block: The log block to emit — a :class:`MarkdownLog` or
            :class:`ToolCallLog` (the :data:`LogBlock` union).
        target: ``"current"`` attaches the log to the conversation/task the
            command is running under; ``"new_task"`` creates a dedicated task
            (subtask of the current context) and routes the log there.
        task_title: Title for the created task when ``target="new_task"``.
        metadata: Optional structured metadata stored alongside the entry.
        base_url: Platform base URL. Falls back to ``ZAMP_BASE_URL``.
        auth_token: API token. Falls back to ``ZAMP_AUTH_TOKEN``.

    Returns:
        :class:`EmitLogResult`. ``ok=False`` on any failure — never raises.
    """
    params: dict[str, Any] = {
        "block": block.model_dump(mode="json"),
        "target": target,
        "context": _resolve_context(),
    }
    if task_title is not None:
        params["task_title"] = task_title
    if metadata:
        params["metadata"] = metadata

    try:
        result = await ActionExecutor.execute(
            EMIT_LOG_ACTION_NAME,
            params,
            base_url=base_url,
            auth_token=auth_token,
            summary="Emit log to current agent context",
        )
        return EmitLogResult(ok=True, result=result)
    except Exception as exc:  # noqa: BLE001 — logging must never break the script
        logger.warning("emit_log failed", error=str(exc))
        return EmitLogResult(ok=False, error=str(exc))
