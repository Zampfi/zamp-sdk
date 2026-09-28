"""Channel context that SDK output (e.g. ``emit_log``) attaches to.

The context reaches the SDK two different ways depending on where the code runs:

* **Inside a sandbox** the runtime injects it as ``ZAMP_*`` environment
  variables, read by :func:`zamp_sdk.context.resolve_context`.
* **Outside a sandbox** there are no such env vars — the host runtime binds it
  here via :func:`bind_channel_context`, so ``emit_log`` / ``emit_text`` / … pick
  it up automatically.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """The channel a context originates from. Restricted to the creation-source
    kinds so an invalid channel fails validation early."""

    CONVERSATION = "conversation"
    TASK = "task"


class ToolExecutionMode(str, Enum):
    """How the tool call this context belongs to runs.

    ``SYNC`` is the agent's own turn. ``ASYNC`` is a background tool call: the channel is
    still the conversation or task it works for, and ``message_id`` is the call's own
    message."""

    SYNC = "sync"
    ASYNC = "async"


class ChannelContext(BaseModel):
    """Streaming/agent-context variables the platform propagates per execution.

    Attached to an action request as its ``channel_context``; the platform forces the
    verified copy into the action's params from there. The six channel fields are
    required — a partial context is not a weaker context, it is no context, which is why
    the runtime injects all six ``ZAMP_*`` variables or none. ``tool_execution_mode`` is
    not one of them: it defaults to ``SYNC``, so a context without it is a foreground one.
    """

    channel_type: ChannelType = Field(description="Channel type — conversation or task")
    channel_id: uuid.UUID = Field(description="Conversation or task id (UUID)")
    streaming_id: str
    message_id: str
    tool_call_id: str
    run_id: str
    tool_execution_mode: ToolExecutionMode = Field(
        default=ToolExecutionMode.SYNC,
        description="sync for the agent's own turn, async inside a background tool call",
    )


_bound_context: ContextVar[Optional[ChannelContext]] = ContextVar("zamp_channel_context", default=None)


def bind_channel_context(context: ChannelContext) -> None:
    """Bind the channel context for the current execution.

    Used outside a sandbox, where the context arrives on the execution input
    rather than as environment variables. Once bound, ``emit_log`` and its
    helpers attach output to this context.
    """
    _bound_context.set(context)


def current_channel_context() -> Optional[ChannelContext]:
    """Return the context bound via :func:`bind_channel_context`, or ``None``."""
    return _bound_context.get()


def clear_channel_context() -> None:
    """Clear any bound channel context (end of execution / tests)."""
    _bound_context.set(None)
