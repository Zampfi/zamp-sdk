"""In-execution step buffer, shared by ``emit_*`` and ``ActionExecutor``.

A host runtime calls :func:`start_log_capture` and then :func:`drain_log_capture`
to return every step the script ran — emitted log blocks and action calls alike —
as part of its result.

This package imports nothing from ``logging`` or ``action_executor``, so both can
import it at module top without an import cycle.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

from zamp_sdk.version import __version__

_log_buffer: ContextVar[Optional[list[dict[str, Any]]]] = ContextVar("zamp_step_buffer", default=None)
_suppress: ContextVar[bool] = ContextVar("zamp_step_suppress", default=False)


def start_log_capture() -> None:
    """Begin accumulating steps for the current execution.

    Used by a runtime that wants to return everything the script streamed as part
    of its result. Blocks keep streaming live regardless; this only turns on the
    second, accumulating sink.
    """
    _log_buffer.set([])


def drain_log_capture() -> list[dict[str, Any]]:
    """Return the steps accumulated since :func:`start_log_capture`.

    Empty list if capture was never started. Safe to call in a ``finally`` to
    collect steps on both success and failure.
    """
    return list(_log_buffer.get() or [])


def capture_active() -> bool:
    """True when steps are being captured — a buffer is set and capture is not
    suppressed. Callers check this to skip building an entry that would be discarded
    (e.g. inside a sandbox, where capture is never started)."""
    return not _suppress.get() and _log_buffer.get() is not None


def capture_step(entry: dict[str, Any]) -> None:
    """Append one step to the capture buffer, if capture is active and not suppressed.

    Every entry carries ``sdk_version`` (as the SDK logger binds it). Appends are
    atomic under the GIL, so concurrent tasks/threads sharing the one buffer append
    safely — only the interleaving (execution order) varies."""
    if _suppress.get():
        return
    buffer = _log_buffer.get()
    if buffer is not None:
        buffer.append({"sdk_version": __version__, **entry})


@contextmanager
def suppress_step_capture() -> Iterator[None]:
    """Suppress step capture within the block. Used by ``emit_log`` around its own
    action call so the emitted block is captured once, not also as an action step."""
    token = _suppress.set(True)
    try:
        yield
    finally:
        _suppress.reset(token)
