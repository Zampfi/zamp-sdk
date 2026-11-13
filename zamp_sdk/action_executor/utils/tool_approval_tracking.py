"""Remember a tool-approval halt, so a host that cannot rely on the raise can still end the phase.

``ToolApprovalRequired`` is an exception, and authored code can lose one: ``asyncio.gather(...,
return_exceptions=True)`` returns it as a value, a never-awaited task drops it, and a ``TaskGroup``
wraps it in an ``ExceptionGroup``. So the halt is also *recorded* here, and the host asks
:func:`pending_tool_approval` once the code is done, whatever it did with the exception.

The record is a mutable holder installed in a context variable by :func:`start_tool_approval_tracking`.
Tasks run in a *copy* of the parent's context, so setting a variable in a child would be invisible to
the parent; the copy shares the same holder object, so appending to it is not.

Host-facing, so deliberately not in ``zamp_sdk.__all__``: the code-executor exposes that whole
surface to authored code, which could then reset the holder and erase the very halt it must not escape.
Hosts import it from ``zamp_sdk.action_executor.utils``.
"""

from contextvars import ContextVar
from typing import Optional

from zamp_sdk.action_executor.utils.errors import ToolApprovalRequired

_holder: ContextVar[Optional[list[ToolApprovalRequired]]] = ContextVar("zamp_tool_approval_holder", default=None)


def start_tool_approval_tracking() -> None:
    """Begin recording tool-approval halts for the current execution.

    Call before running the authored code, in the context that will read the result.
    """
    _holder.set([])


def pending_tool_approval() -> Optional[ToolApprovalRequired]:
    """The first halt recorded since :func:`start_tool_approval_tracking`, or ``None``.

    Safe to call after the code returned, raised, or was torn down by a task group.
    """
    halts = _holder.get()
    return halts[0] if halts else None


def record_tool_approval(halt: ToolApprovalRequired) -> None:
    """Record ``halt`` if tracking is active; the first one wins. Called by the SDK, not hosts."""
    halts = _holder.get()
    if halts is not None and not halts:
        halts.append(halt)
