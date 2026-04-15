from enum import Enum
from typing import Any


class ExecutionMode(str, Enum):
    """Public execution modes exposed by the Zamp SDK."""

    SYNC = "SYNC"
    ASYNC = "ASYNC"
    INLINE = "INLINE"


def resolve_ah_execution_mode(mode: ExecutionMode | None) -> Any | None:
    """Map the public ``ExecutionMode`` to the ActionsHub ``ExecutionMode``.

    Lazy-imports ``zamp_public_workflow_sdk`` so that the public ``zamp-sdk``
    package can be installed without the private workflow SDK being present.
    Callers must only invoke this from execution paths where the private SDK
    is known to be available (i.e. inside a Temporal worker process, not
    inside a Modal sandbox).

    Returns ``None`` when ``mode`` is ``None``.
    """
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
