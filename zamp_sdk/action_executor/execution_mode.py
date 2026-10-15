from enum import Enum
from typing import Any


class ExecutionMode(str, Enum):
    """Public execution modes exposed by the Zamp SDK.

    ``INLINE`` on the API route is forwarded to the platform, which runs the action in-process
    and returns the result in the POST response. It needs a platform-side opt-in per action;
    otherwise the platform returns 422. The gateway route ignores ``execution_mode``.
    """

    SYNC = "SYNC"
    ASYNC = "ASYNC"
    INLINE = "INLINE"


def resolve_ah_execution_mode(mode: ExecutionMode | None) -> Any | None:
    if mode is None:
        return None

    from zamp_public_workflow_sdk.actions_hub.constants import (
        ExecutionMode as AHExecutionMode,
    )

    mapping = {
        ExecutionMode.SYNC: AHExecutionMode.TEMPORAL_SYNC,
        ExecutionMode.ASYNC: AHExecutionMode.TEMPORAL_ASYNC,
        ExecutionMode.INLINE: AHExecutionMode.INLINE,
    }
    return mapping[mode]
