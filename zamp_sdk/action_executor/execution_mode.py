from enum import Enum
from typing import Any


class ExecutionMode(str, Enum):
    """Public execution modes exposed by the Zamp SDK.

    ``SYNC``, ``ASYNC`` and ``DURABLE`` all run the action durably on Temporal (the API route
    POSTs then polls). ``INLINE`` runs it in-process with a single attempt; the API route needs
    the platform-side per-action opt-in, otherwise the platform returns 422. The gateway route
    ignores ``execution_mode``.
    """

    SYNC = "SYNC"
    ASYNC = "ASYNC"
    DURABLE = "DURABLE"
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
        ExecutionMode.DURABLE: AHExecutionMode.TEMPORAL_SYNC,
        ExecutionMode.INLINE: AHExecutionMode.INLINE,
    }
    return mapping[mode]
