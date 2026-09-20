"""Severity of a script's own log line, and the threshold it is gated against."""

from enum import IntEnum


class LogLevel(IntEnum):
    """How important a log line is, and which lines a configured threshold lets through.

    ``IntEnum`` because the gate is an ordering comparison (``level >= configured``), not an
    identity check.

    The numbers are Python's stdlib levels, and the gaps between them are the reason to use
    them rather than 1/2/3. ``WARNING`` is deliberately absent — nothing needs it yet, and an
    unused level is one more thing an author has to guess the meaning of — but 30 is left free
    so adding it later inserts rather than renumbers. Renumbering would quietly change what an
    already-set ``ZAMP_LOG_LEVEL``, or an integer a caller passed, resolves to.
    """

    DEBUG = 10
    INFO = 20
    ERROR = 40


# Level applied when neither the script nor the environment says otherwise. INFO, so
# ``emit_debug`` is the line an author can leave in the code permanently and only see when
# they go looking for it.
DEFAULT_LEVEL = LogLevel.INFO
