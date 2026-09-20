"""The SDK's own logging of action calls — everything it emits on the script's behalf.

``ActionExecutor.execute`` opens a log before it dispatches and closes it after, so a script no
longer has to mirror its own action calls into the live message. All of the policy lives here
rather than at the call site: which routes log and which actions never do.

Three plain functions, no object and no context manager. This sits inside every action call, in
a sandbox script and in a code-executor workflow, so the path stays as short as it can be: when
logging is off, :func:`open_action_log` returns ``None`` after one cheap check and allocates
nothing at all.

The block id is the only state, and handing it between the two halves makes the pairing correct
by construction: ``None`` means this call was not logged, so the closing half has nothing to do
and cannot leave a half-shown pair behind.

This module imports the emit helpers normally. ``action_executor`` cannot: importing anything
under ``zamp_sdk.logging`` runs this package's ``__init__``, which imports ``logging.py``, which
imports ``action_executor`` — half-initialised, if that is where the chain started. So the one
import that has to stay inside a function is ``execute``'s import of these helpers, by which
time every module is loaded.
"""

from __future__ import annotations

from typing import Any, Optional

from zamp_sdk.logger import get_logger
from zamp_sdk.logging.constants import NON_LOGGABLE_ACTIONS
from zamp_sdk.logging.log_control import auto_action_logs_enabled
from zamp_sdk.logging.logging import emit_tool_result, emit_tool_use

logger = get_logger(__name__)


def _should_log(action_name: str, log_action: Optional[bool]) -> bool:
    """Whether this action call gets an auto-log.

    The first check is correctness, not preference, so nothing overrides it: dispatching
    ``emit_log`` is how a log line is *sent*, so logging that call would call it again.
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
    should_log: bool = True,
    log_action: Optional[bool] = None,
) -> Optional[str]:
    """Show the call as running, and return the block id that will close it.

    Args:
        action_name: The action being dispatched; the block's name.
        params: The action's input, shown as the block's input.
        summary: The caller's own description of the call, used as the block's display title.
            Without one the platform falls back to the action's configured display name.
        should_log: False for a route that is never logged — an in-process call on the worker
            that already owns the action is plumbing, not a tool call the user is waiting on.
        log_action: An explicit per-call override, winning over every other consideration.

    Returns:
        The block id, or ``None`` when this call is not logged — including when the emit itself
        failed. Hand it to :func:`close_action_log` or :func:`fail_action_log`.

    Never raises. Logging is telemetry wrapped around somebody's real work, and a failure to
    describe that work must not become a failure to do it.
    """
    if not (should_log and _should_log(action_name, log_action)):
        return None
    try:
        return await emit_tool_use(action_name, display_title=summary, input=params, auto=True)
    except Exception as exc:
        logger.warning("could not open the action log", action_name=action_name, error=repr(exc))
        return None


async def close_action_log(block_id: Optional[str], action_name: str, result: Any) -> None:
    """Complete the call's block with what it returned. Never raises."""
    await _close(block_id, action_name, result)


async def fail_action_log(block_id: Optional[str], action_name: str, error: BaseException) -> None:
    """Complete the call's block with the failure, so it does not sit there running.

    An open block renders as running forever, which reads as a hung system rather than a call
    that failed. Never raises.
    """
    await _close(block_id, action_name, f"FAILED: {error}")


async def _close(block_id: Optional[str], action_name: str, content: Any) -> None:
    """Emit the closing half, unless this call never opened one."""
    if block_id is None:
        return
    try:
        await emit_tool_result(block_id, content, name=action_name, auto=True)
    except Exception as exc:
        logger.warning("could not close the action log", action_name=action_name, error=repr(exc))
