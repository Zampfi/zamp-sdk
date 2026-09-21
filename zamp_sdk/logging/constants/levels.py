"""Severity of a script's own log line, and the threshold it is gated against."""

from enum import StrEnum


class LogLevel(StrEnum):
    """A level, written and read as the word for it: ``"debug"`` / ``"info"`` / ``"error"``.

    No ``WARNING`` — nothing needs one yet, and :data:`LOG_LEVEL_SEVERITY` leaves room for it.
    """

    DEBUG = "debug"
    INFO = "info"
    ERROR = "error"

    @classmethod
    def _missing_(cls, value: object) -> "LogLevel | None":
        """Accept any casing. A level is usually typed into a skill's JSON, where ``"INFO"`` is
        not a mistake worth failing a run over."""
        if isinstance(value, str):
            return cls.__members__.get(value.strip().upper())
        return None

    @property
    def severity(self) -> int:
        """Rank for threshold comparison. Explicit because these are strings, and comparing
        them directly sorts alphabetically — ``debug < error < info``, which is wrong."""
        return LOG_LEVEL_SEVERITY[self]


# Stdlib numbers, so 30 stays free for WARNING. Below the class because it keys on its members.
LOG_LEVEL_SEVERITY = {LogLevel.DEBUG: 10, LogLevel.INFO: 20, LogLevel.ERROR: 40}

# INFO, so ``emit_debug`` is the line an author leaves in and only sees when they look for it.
DEFAULT_LEVEL = LogLevel.INFO
