"""How one run logs — one object that travels with the run rather than ambient flags.

That matters inside a Temporal workflow: an emit is a recorded command, so a setting read from
the environment could differ between the first execution and a replay and change the command
sequence. Config carried on the input is recorded in history, so a replay sees what the first
run saw.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zamp_sdk.logging.constants import DEFAULT_LEVEL, LogLevel


class LoggingConfig(BaseModel):
    """The logging rules in force for one run.

    The first two fields govern what the *script* emits, the third what the *SDK* emits for it.
    Separate, so silencing one never silences the other.
    """

    level: LogLevel = Field(
        default=DEFAULT_LEVEL,
        description=(
            "Lowest level of the script's own lines to show: 'debug', 'info' or 'error'. At "
            "the default, 'info', emit_debug is silent."
        ),
    )
    enabled: bool = Field(
        default=True,
        description=(
            "False silences all of the script's own lines whatever their level — there is no "
            "level above 'error', so all-off cannot be expressed as a threshold."
        ),
    )
    auto_action_logs: bool = Field(
        default=False,
        description=(
            "Whether the SDK logs each action call on the script's behalf. Off by default, so "
            "upgrading the SDK alone changes nothing about what a running script produces."
        ),
    )
