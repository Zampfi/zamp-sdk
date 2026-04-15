from enum import Enum
from typing import Any


class ExecutionMode(str, Enum):
    """Public execution modes exposed by the Zamp SDK."""

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
