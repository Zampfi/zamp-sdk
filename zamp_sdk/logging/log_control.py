"""Policy and state for what the SDK logs: the levels and the two switches.

Two gates, deliberately separate and separately named:

* **The user gate** (:func:`configure_logging`) governs only what the script itself emits —
  ``emit_text`` / ``emit_info`` / ``emit_debug`` / ``emit_error`` / ``emit_log``.
* **The auto gate** (:func:`configure_auto_action_logs`) governs only what the SDK emits on the
  script's behalf — the per-action tool-call blocks and ``datasets.stream``'s summary.

Silencing your own logs must never silence the platform's, and vice versa, so neither switch
reaches the other's state.

One :class:`LoggingConfig` is all the state there is, and it travels with the run rather than
being assembled from ambient values: a host binds it (the code executor, from its workflow
input), a script can replace it through ``configure_logging`` / ``configure_auto_action_logs``,
and a plain process with neither falls back to the environment.
This module imports nothing from ``zamp_sdk.logging``'s other modules or from
``zamp_sdk.action_executor``, so both can reach it without the import cycle described in that
package's ``auto`` module. Constants live in ``zamp_sdk.logging.constants``.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Optional

from zamp_sdk.context.env import (
    ENV_AUTO_ACTION_LOGS,
    ENV_LOG_ENABLED,
    ENV_LOG_LEVEL,
)
from zamp_sdk.logger import get_logger
from zamp_sdk.logging.constants import LogLevel
from zamp_sdk.logging.models.config import LoggingConfig

logger = get_logger(__name__)

# This run's rules. The host binds it (the code executor, from its workflow input); a script can
# replace it through ``configure_logging``. None means nobody has, so the environment decides.
_config: ContextVar[Optional[LoggingConfig]] = ContextVar("zamp_logging_config", default=None)


def _parse_level(value: object) -> LogLevel:
    """A :class:`LogLevel` from a level or its name, e.g. ``LogLevel.DEBUG`` or ``"debug"``.

    Raises on anything else: this only ever reads what a script typed into
    ``configure_logging``, and a value that means nothing is a typo worth saying so about —
    silently ignoring it would leave the author wondering why their level did not apply.
    """
    if isinstance(value, LogLevel):
        return value
    if isinstance(value, str):
        try:
            return LogLevel[value.strip().upper()]
        except KeyError:
            pass
    valid = ", ".join(level.name.lower() for level in LogLevel)
    raise ValueError(f"{value!r} is not a known log level (expected one of: {valid})")


def bind_logging_config(config: Optional[LoggingConfig]) -> None:
    """Set the rules for this run, from a host that was handed them.

    The code executor calls this at the start of every run with the config on its input, which
    is what keeps the rules identical across a replay and stops one run's settings reaching the
    next on a long-lived worker.

    ``None`` is accepted and means the run carries no config — a workflow that started before
    the field existed, replaying now. The defaults apply, and they are bound *explicitly* rather
    than left to fall through to the environment: an environment read inside a workflow is the
    non-determinism this whole arrangement exists to avoid.
    """
    _config.set(config or LoggingConfig())


def current_logging_config() -> LoggingConfig:
    """The rules in force: what was bound or configured, else what the environment says."""
    bound = _config.get()
    return _config_from_env() if bound is None else bound


def _config_from_env() -> LoggingConfig:
    """The config for a process nobody bound one into — a sandbox script.

    The same model a workflow gets, assembled from the environment because a plain process has
    no input to carry it on. A workflow that *was* bound a config never reaches here, which is
    what keeps it from reading the environment at all.

    Each variable is read on its own: an unset or unreadable one leaves that field at its
    default rather than discarding the rest. Nothing here raises — the platform sets these, and
    a script should not die because a logging preference was malformed.
    """
    updates: dict[str, object] = {}
    if (level := _env_level()) is not None:
        updates["level"] = level
    if (enabled := _env_flag(ENV_LOG_ENABLED)) is not None:
        updates["enabled"] = enabled
    if (auto := _env_flag(ENV_AUTO_ACTION_LOGS)) is not None:
        updates["auto_action_logs"] = auto
    return LoggingConfig().model_copy(update=updates)


def _env_flag(name: str) -> Optional[bool]:
    """A boolean environment variable, or None when unset or unrecognised.

    Compared rather than cast: an environment variable only carries strings, so ``bool("false")``
    would be True.
    """
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true"):
        return True
    if raw in ("0", "false"):
        return False
    return None


def _env_level() -> Optional[LogLevel]:
    """The level from the environment, or None when unset or unrecognised.

    Unrecognised resolves to None rather than raising, unlike a level a script passes to
    ``configure_logging``: that is someone typing and worth correcting, this is the platform's
    and not worth failing a run over.
    """
    raw = os.environ.get(ENV_LOG_LEVEL, "").strip().upper()
    return LogLevel[raw] if raw in LogLevel.__members__ else None


def configure_logging(
    *,
    level: object = None,
    enabled: Optional[bool] = None,
) -> None:
    """Configure what **this script's own** log lines do.

    Affects ``emit_text`` / ``emit_info`` / ``emit_debug`` / ``emit_error`` / ``emit_log`` and
    nothing else. The platform's automatic per-action logs are a separate switch —
    :func:`configure_auto_action_logs` — so silencing yourself never silences those.

    Args:
        level: Minimum level to emit, as a :class:`LogLevel` or its name (``"debug"``).
            Defaults to ``INFO``, at which ``emit_debug`` is silent. Raises on an unknown name.
        enabled: ``False`` silences every one of your own emits, whatever their level.

    Both arguments are optional; omitting one leaves it as it was.
    """
    updates: dict[str, object] = {}
    if level is not None:
        updates["level"] = _parse_level(level)
    if enabled is not None:
        updates["enabled"] = bool(enabled)
    if updates:
        _config.set(current_logging_config().model_copy(update=updates))


def configure_auto_action_logs(enabled: bool) -> None:
    """Turn the SDK's automatic per-action logging on or off for this script.

    Governs the tool-call blocks the SDK emits for you, and ``datasets.stream``'s summary. Your
    own ``emit_*`` calls are unaffected — those are :func:`configure_logging`.

    Wins over whatever the run was started with, so a script can opt in where the platform has
    not enabled it.
    """
    _config.set(current_logging_config().model_copy(update={"auto_action_logs": bool(enabled)}))


def should_emit(level: LogLevel) -> bool:
    """Whether a log line of ``level`` written by the script itself is shown.

    Reads the config once: this runs on every one of the script's log lines.
    """
    config = current_logging_config()
    return config.enabled and level >= config.level


def auto_action_logs_enabled() -> bool:
    """Whether the SDK should log action calls on the script's behalf.

    Default off: the feature is enabled per environment during rollout, so that upgrading the
    SDK on its own changes nothing about what a running script produces.
    """
    return current_logging_config().auto_action_logs
