"""Channel context that SDK output (e.g. ``emit_log``) attaches to.

The context reaches the SDK two different ways depending on where the code runs:

* **Inside a Pantheon sandbox** the runtime injects it as ``ZAMP_*`` environment
  variables, read by :func:`zamp_sdk.context.resolve_context`.
* **Inside the code executor** (a Temporal worker, *not* a sandbox) there are no
  such env vars. The ``CodeExecutorWorkflow`` receives the context from Pantheon
  on the Nexus trigger and binds it here via :func:`bind_channel_context`, so
  ``emit_log`` / ``emit_text`` / … pick it up automatically.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from pydantic import BaseModel, Field


class ChannelContext(BaseModel):
    """Streaming/agent-context variables the platform propagates per execution.

    Field names and shape match the platform-side ``EmitLogContext`` so the
    ``emit_log`` action payload stays wire-compatible.
    """

    channel_type: str = Field(description="'conversation' | 'task' — current channel type")
    channel_id: str = Field(description="Conversation or task id of the current context")
    streaming_id: str
    message_id: str
    tool_call_id: str
    run_id: str


_bound_context: ContextVar[Optional[ChannelContext]] = ContextVar(
    "zamp_channel_context", default=None
)


def bind_channel_context(context: ChannelContext) -> None:
    """Bind the channel context for the current execution.

    Used outside the sandbox (e.g. the ``CodeExecutorWorkflow``), where the
    context arrives on the workflow input rather than as environment variables.
    Once bound, ``emit_log`` and its helpers attach output to this context.
    """
    _bound_context.set(context)


def current_channel_context() -> Optional[ChannelContext]:
    """Return the context bound via :func:`bind_channel_context`, or ``None``."""
    return _bound_context.get()


def clear_channel_context() -> None:
    """Clear any bound channel context (end of execution / tests)."""
    _bound_context.set(None)
