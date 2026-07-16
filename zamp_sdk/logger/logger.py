"""SDK logger factory shared across the SDK.

Every SDK logger is created through :func:`get_logger` so the current SDK
version is bound to — and therefore printed with — every log line, including
the progress logs emitted before ``emit_log`` reaches the platform.
"""

from __future__ import annotations

from typing import Any

import structlog

from zamp_sdk.version import __version__


def get_logger(name: str) -> Any:
    """Return a structlog logger pre-bound with the SDK version.

    The ``sdk_version`` key rides along on every event this logger emits, so
    each log line carries the version regardless of when it fires.

    Args:
        name: Logger name, conventionally the calling module's ``__name__``.
    """
    return structlog.get_logger(name).bind(sdk_version=__version__)
