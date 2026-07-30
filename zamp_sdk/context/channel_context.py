"""Channel context that SDK output (e.g. ``emit_log``) attaches to.

Inside a sandbox the runtime injects it as ``ZAMP_*`` environment variables, read
by :func:`zamp_sdk.context.resolve_context` and validated into a
:class:`ChannelContext` by :func:`zamp_sdk.context.resolve_channel_context`.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """The channel a context originates from. Restricted to the creation-source
    kinds so an invalid channel fails validation early."""

    CONVERSATION = "conversation"
    TASK = "task"


class ChannelContext(BaseModel):
    """Streaming/agent-context variables the platform propagates per execution.

    Field names and shape match the platform-side ``EmitLogContext`` so the
    ``emit_log`` action payload stays wire-compatible.
    """

    channel_type: ChannelType = Field(description="Channel type — conversation or task")
    channel_id: uuid.UUID = Field(description="Conversation or task id (UUID)")
    streaming_id: str
    message_id: str
    tool_call_id: str
    run_id: str
