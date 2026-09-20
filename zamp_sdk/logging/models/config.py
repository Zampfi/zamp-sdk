"""How one run logs.

A single object rather than a scattering of flags, and it travels *with* the run: pantheon
decides it, the code executor receives it on its input and binds it, and the authored code sees
the same values. Nobody has to read ambient state to find out what the rules are.

That matters most inside a Temporal workflow. Reading an environment variable there is a
non-deterministic input — an emit is a recorded command, so if the variable changed between the
original execution and a replay the command sequence would no longer match and the run would
fail. Config carried on the workflow's input is recorded in history, so a replay sees exactly
what the first run saw.

Defaults are what a run gets when nobody says otherwise: the script's own lines at ``INFO``, and
the SDK's automatic action logs off until the platform turns them on.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zamp_sdk.logging.constants import DEFAULT_LEVEL, LogLevel


class LoggingConfig(BaseModel):
    """The logging rules in force for one run.

    The first two fields govern only what the *script* emits; the third governs only what the
    *SDK* emits on its behalf. They are separate so that silencing your own lines never silences
    the platform's action logs, and turning those off never silences yours.
    """

    level: LogLevel = Field(
        default=DEFAULT_LEVEL,
        description=(
            "Lowest level of the script's own lines to show: 'debug', 'info' or 'error'. At "
            "the default, 'info', ``emit_debug`` is silent — the line an author can leave in "
            "the code and only see when they go looking for it."
        ),
    )
    enabled: bool = Field(
        default=True,
        description=(
            "False silences every one of the script's own lines whatever their level. There is "
            "no level above ERROR, so an all-off switch cannot be expressed as a threshold."
        ),
    )
    auto_action_logs: bool = Field(
        default=False,
        description=(
            "Whether the SDK logs each action call on the script's behalf. Off by default, so "
            "upgrading the SDK alone changes nothing about what a running script produces; the "
            "platform turns it on per environment."
        ),
    )
