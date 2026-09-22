"""The blocks the SDK emits for an action call, so a script need not mirror its own calls.

The block id is the only state: ``None`` means the call was not logged, so the closing half
has nothing to do and cannot leave a half-shown pair behind.

Plain functions, no context manager — this sits inside every action call, so when logging is
off :func:`open_action_log` returns after one cheap check.
"""

from __future__ import annotations

from typing import Any, Optional

from zamp_sdk.logger import get_logger
from zamp_sdk.logging.constants import NON_LOGGABLE_ACTIONS
from zamp_sdk.logging.log_control import auto_action_logs_enabled
from zamp_sdk.logging.logging import _emit_tool_use_block, emit_tool_result

logger = get_logger(__name__)


def _should_log(action_name: str, log_action: Optional[bool]) -> bool:
    """Whether this call gets a block. Only the routes that log ask.

    The first check is correctness, not preference: dispatching ``emit_log`` is how a line is
    *sent*, so logging that call would call it again.
    """
    if action_name in NON_LOGGABLE_ACTIONS:
        return False
    if log_action is not None:
        return log_action
    return auto_action_logs_enabled()


async def open_action_log(
    action_name: str,
    params: dict[str, Any],
    *,
    summary: Optional[str] = None,
    log_action: Optional[bool] = None,
) -> Optional[str]:
    """Show the call as running; return the id that closes it, or ``None`` if it was not shown.

    ``summary`` becomes the block's title; without one the platform falls back to the action's
    configured display name. ``log_action`` overrides the run's setting for this call.

    Never raises — a failure to describe the work must not become a failure to do it.
    """
    if not _should_log(action_name, log_action):
        return None
    try:
        block_id, result = await _emit_tool_use_block(action_name, display_title=summary, input=params, auto=True)
    except Exception as exc:
        logger.warning("could not open the action log", action_name=action_name, error=repr(exc))
        return None
    if not result.ok:
        # Delivery failure comes back as a value, not a raise. None keeps the pair honest: a
        # closing block under one that never appeared would render as a result with no call.
        logger.warning(
            "the action log did not open; not closing it either",
            action_name=action_name,
            error=result.error,
        )
        return None
    return block_id


async def close_action_log(block_id: Optional[str], action_name: str, result: Any) -> None:
    """Complete the block with what the caller decided to show. Never raises.

    Takes the value as given: what a result means depends on the route, which is the
    dispatcher's knowledge, not this module's.
    """
    await _close(block_id, action_name, result)


async def fail_action_log(block_id: Optional[str], action_name: str, error: BaseException) -> None:
    """Close the block as failed. An open one renders as running forever, which reads as a hung
    system rather than a call that failed. Never raises."""
    await _close(block_id, action_name, f"FAILED: {error}")


async def _close(block_id: Optional[str], action_name: str, content: Any) -> None:
    """Emit the closing half, unless this call never opened one."""
    if block_id is None:
        return
    try:
        await emit_tool_result(block_id, content, name=action_name, auto=True)
    except Exception as exc:
        logger.warning("could not close the action log", action_name=action_name, error=repr(exc))
