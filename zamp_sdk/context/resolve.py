from __future__ import annotations

import os
from typing import Any

from zamp_sdk.context.env import (
    ENV_CHANNEL_ID,
    ENV_CHANNEL_TYPE,
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
