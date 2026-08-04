from __future__ import annotations

import os
from typing import Any, Optional

from zamp_sdk.context.channel_context import ChannelContext, current_channel_context
from zamp_sdk.context.env import (
    ENV_CHANNEL_ID,
    ENV_CHANNEL_TYPE,
    ENV_MESSAGE_ID,
    ENV_RUN_ID,
    ENV_STREAMING_ID,
    ENV_TOOL_CALL_ID,
)
from zamp_sdk.context.execution_host import ExecutionHost, current_execution_host


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

    The execution host decides the source, the same fact that decides how actions
    dispatch: an ``ACTIONS_HUB`` host has a workflow that bound the context in-process,
    while an ``API`` host is a standalone process the runtime fed through ``ZAMP_*``
    environment variables. Sent once when calling the platform so actions don't each have
    to attach it.

    Deciding by host rather than by trying both matters on the API path: code running in a
    sandbox can import and call :func:`bind_channel_context` itself, and a bound value is
    never consulted there, so it cannot redirect its own output to a channel the runtime
    did not give it.

    Resolving the context is best-effort and must never break the action call it
    decorates, so *any* failure here resolves to None and the action goes through
    without a context.
    """
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        return current_channel_context()
    try:
        return ChannelContext(**resolve_context())
    except Exception:
        return None
