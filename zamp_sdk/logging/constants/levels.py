"""Severity of a script's own log line, and the threshold it is gated against."""

from enum import StrEnum


class LogLevel(StrEnum):
    """How important a log line is, and which lines a configured threshold lets through.

    A string enum, so a level is written and read as the word for it — ``"debug"`` in a skill's
    ``logging_config``, in an environment variable and in the tool schema the model sees. A
    number would make every caller look up which of 10/20/40 they meant.

    ``WARNING`` is deliberately absent: nothing needs it yet, and an unused level is one more
    thing an author has to guess the meaning of. :data:`LOG_LEVEL_SEVERITY` leaves room for it.
    """

    DEBUG = "debug"
    INFO = "info"
    ERROR = "error"

    @classmethod
    def _missing_(cls, value: object) -> "LogLevel | None":
        """Accept what older callers and hand-written config send, not just the exact word.

        Levels used to be the stdlib numbers, so a config written against an earlier SDK — or
        replayed from a workflow that recorded one — carries ``20`` where this now expects
        ``"info"``. Both resolve, so upgrading the SDK cannot make an existing config invalid.
        Casing is forgiven for the same reason: ``"INFO"`` is not a mistake worth failing on.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return next((lvl for lvl, rank in LOG_LEVEL_SEVERITY.items() if rank == value), None)
        if isinstance(value, str):
            return cls.__members__.get(value.strip().upper())
        return None

    @property
    def severity(self) -> int:
        """Rank for threshold comparison — higher is more severe.

        Ordering has to be explicit rather than the enum's own ``<``: these are strings, and
        comparing them directly would sort alphabetically, making ``debug < error < info``.
        """
        return LOG_LEVEL_SEVERITY[self]


# Rank of each level, read by :attr:`LogLevel.severity`. Defined after the class because it
# keys on its members. Python's stdlib numbers, so they read the same way to anyone who knows
# ``logging``, and the gaps leave 30 free for ``WARNING`` without renumbering the rest.
LOG_LEVEL_SEVERITY = {LogLevel.DEBUG: 10, LogLevel.INFO: 20, LogLevel.ERROR: 40}

# Level applied when neither the script nor the environment says otherwise. INFO, so
# ``emit_debug`` is the line an author can leave in the code permanently and only see when
# they go looking for it.
DEFAULT_LEVEL = LogLevel.INFO
