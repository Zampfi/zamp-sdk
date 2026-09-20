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
        """Also accept any casing, and the stdlib numbers levels used to be, so upgrading the
        SDK cannot invalidate a config already written or recorded in a workflow's history."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return next((lvl for lvl, rank in LOG_LEVEL_SEVERITY.items() if rank == value), None)
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
