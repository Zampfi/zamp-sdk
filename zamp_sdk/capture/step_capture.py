"""In-execution step buffer, shared by ``emit_*`` and ``ActionExecutor``.

A host runtime calls :func:`start_log_capture` and then :func:`drain_log_capture`
to return every step the script ran — emitted log blocks and action calls alike —
as part of its result.

This package imports nothing from ``logging`` or ``action_executor``, so both can
import it at module top without an import cycle.
"""

import json
from contextvars import ContextVar
from typing import Any, Optional

from zamp_sdk.version import __version__

_log_buffer: ContextVar[Optional[list[str]]] = ContextVar("zamp_step_buffer", default=None)


def start_log_capture() -> None:
    """Begin accumulating steps for the current execution.

    Not for an ``api`` execution host: nothing there drains the buffer, so steps would
    accumulate for the life of the process.
    """
    _log_buffer.set([])


def drain_log_capture() -> list[str]:
    """Return and clear the steps accumulated since :func:`start_log_capture`.

    Each item is one step as a JSON string, serialized once when it was captured.

    Clearing deactivates capture, so a later append or a reused execution context
    can't leak stale steps into the next drain. Empty list if capture was never
    started. Safe to call in a ``finally`` to collect steps on success and failure.
    """
    buffer = _log_buffer.get()
    _log_buffer.set(None)
    return list(buffer or [])


def capture_active() -> bool:
    """True when steps are being captured. Callers check this to skip building an entry that
    would be discarded (e.g. inside a sandbox, where capture is never started)."""
    return _log_buffer.get() is not None


def capture_step(entry: dict[str, Any]) -> None:
    """Append one step to the capture buffer, if capture is active and not suppressed.

    Every entry carries ``sdk_version`` (as the SDK logger binds it). Appends are
    atomic under the GIL, so concurrent tasks/threads sharing the one buffer append
    safely — only the interleaving (execution order) varies.

    The entry is serialized here, once, with ``default=str`` for values JSON can't carry
    (datetimes, Decimals...). Anything still unserializable (a circular reference) raises
    to the caller, which decides whether to drop the step."""
    buffer = _log_buffer.get()
    if buffer is not None:
        buffer.append(json.dumps({"sdk_version": __version__, **entry}, default=str))
