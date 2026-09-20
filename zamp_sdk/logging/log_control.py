"""What the SDK logs: one :class:`LoggingConfig`, and the two switches over it.

:func:`configure_logging` governs only what the script emits; :func:`configure_auto_action_logs`
only what the SDK emits for it. Neither switch reaches the other's state — silencing your own
lines must not silence the platform's.

Imports nothing from this package's other modules, so both can reach it without a cycle.
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

# This run's rules. None means nobody bound any, so the environment decides.
_config: ContextVar[Optional[LoggingConfig]] = ContextVar("zamp_logging_config", default=None)


def _parse_level(value: object) -> LogLevel:
    """A level from one, or its name in any casing. Raises on anything else: this reads what a
    script typed, and a silently ignored typo leaves the author wondering why it did not apply.
    """
    if isinstance(value, LogLevel):
        return value
    if isinstance(value, str):
        try:
            return LogLevel(value.strip().lower())
        except ValueError:
            pass
    valid = ", ".join(LogLevel)
    raise ValueError(f"{value!r} is not a known log level (expected one of: {valid})")


def bind_logging_config(config: Optional[LoggingConfig]) -> None:
    """Set the rules for this run, from a host that was handed them on its input.

    Keeps them identical across a replay, and stops one run's settings reaching the next on a
    long-lived worker. ``None`` binds the defaults *explicitly* rather than falling through to
    the environment — an environment read inside a workflow is the non-determinism this avoids.
    """
    _config.set(config or LoggingConfig())


def current_logging_config() -> LoggingConfig:
    """The rules in force: what was bound or configured, else what the environment says."""
    bound = _config.get()
    return _config_from_env() if bound is None else bound


def _config_from_env() -> LoggingConfig:
    """The config for a process nobody bound one into — a sandbox script, which has no input to
    carry it on. Each variable is read on its own, so one bad value costs that field, not the
    rest. Never raises: a malformed preference must not kill a script."""
    updates: dict[str, object] = {}
    if (level := _env_level()) is not None:
        updates["level"] = level
    if (enabled := _env_flag(ENV_LOG_ENABLED)) is not None:
        updates["enabled"] = enabled
    if (auto := _env_flag(ENV_AUTO_ACTION_LOGS)) is not None:
        updates["auto_action_logs"] = auto
    return LoggingConfig().model_copy(update=updates)


def _env_flag(name: str) -> Optional[bool]:
    """A boolean variable, or None. Compared rather than cast — ``bool("false")`` is True."""
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true"):
        return True
    if raw in ("0", "false"):
        return False
    return None


def _env_level() -> Optional[LogLevel]:
    """The level from the environment, or None. Unrecognised is ignored rather than raised on:
    unlike a level a script typed, this one is the platform's and not worth failing a run over.
    """
    raw = os.environ.get(ENV_LOG_LEVEL, "").strip().lower()
    return LogLevel(raw) if raw in set(LogLevel) else None


def configure_logging(
    *,
    level: object = None,
    enabled: Optional[bool] = None,
) -> None:
    """Configure what **this script's own** log lines do. Omitting an argument leaves it as it was.

    Args:
        level: Lowest level to emit — ``"debug"`` / ``"info"`` / ``"error"``. Raises on an
            unknown name.
        enabled: ``False`` silences all of your own lines, whatever their level.

    The SDK's automatic per-action logs are a separate switch, so this never touches them.
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

    Wins over whatever the run was started with. Your own ``emit_*`` calls are unaffected —
    those are :func:`configure_logging`.
    """
    _config.set(current_logging_config().model_copy(update={"auto_action_logs": bool(enabled)}))


def should_emit(level: LogLevel) -> bool:
    """Whether a line of ``level`` written by the script is shown. Runs on every one."""
    config = current_logging_config()
    return config.enabled and level.severity >= config.level.severity


def auto_action_logs_enabled() -> bool:
    """Whether the SDK logs action calls for the script. Off by default, so upgrading the SDK
    alone changes nothing about what a running script produces."""
    return current_logging_config().auto_action_logs
