from __future__ import annotations

import os
from typing import Any, Optional

from zamp_sdk.context.channel_context import ChannelContext
from zamp_sdk.context.env import (
    ENV_CHANNEL_ID,
    ENV_CHANNEL_TYPE,
    ENV_INSIDE_SANDBOX,
    ENV_MESSAGE_ID,
    ENV_RUN_ID,
    ENV_STREAMING_ID,
    ENV_TOOL_CALL_ID,
)


def resolve_context() -> dict[str, Any]:
    """Read the agent context the runtime injected into the environment.

    Only keys that are actually set are returned, so an unset variable never
    overwrites context the server already holds. Shared by every SDK feature
    that attaches output to the running agent.
    """
    ctx = {
        "channel_type": os.environ.get(ENV_CHANNEL_TYPE),
        "channel_id": os.environ.get(ENV_CHANNEL_ID),
        "streaming_id": os.environ.get(ENV_STREAMING_ID),
        "message_id": os.environ.get(ENV_MESSAGE_ID),
        "tool_call_id": os.environ.get(ENV_TOOL_CALL_ID),
        "run_id": os.environ.get(ENV_RUN_ID),
    }
    return {k: v for k, v in ctx.items() if v}


def resolve_channel_context() -> Optional[ChannelContext]:
    """The caller's full channel context as a validated ``ChannelContext``, or None.

    Inside a sandbox it comes from the ``ZAMP_*`` env vars the runtime injected —
    None if they don't form a complete, valid context. Sent once when calling the
    platform so actions don't each have to attach it.

    Resolving the context is best-effort and must never break the action call it
    decorates, so *any* failure here resolves to None and the action goes through
    without a context.
    """
    if os.environ.get(ENV_INSIDE_SANDBOX) == "true":
        try:
            return ChannelContext(**resolve_context())
        except Exception:
            return None
    return None
