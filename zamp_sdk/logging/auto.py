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
from zamp_sdk.logging.constants import ACTION_ENVELOPE_KEYS, NON_LOGGABLE_ACTIONS
from zamp_sdk.logging.log_control import auto_action_logs_enabled
from zamp_sdk.logging.logging import _emit_tool_use_block, emit_tool_result

logger = get_logger(__name__)


def _should_log(action_name: str, log_action: Optional[bool], logged_route: bool) -> bool:
    """Whether this action call gets an auto-log.

    The first check is correctness, not preference, so nothing overrides it: dispatching
    ``emit_log`` is how a log line is *sent*, so logging that call would call it again.

    Everything after it is preference, and an explicit ``log_action`` settles it — including on
    a route that is not logged by default. ``logged_route`` is that default, not a veto: an
    in-process call is plumbing *unless the caller says otherwise*.
    """
    if action_name in NON_LOGGABLE_ACTIONS:
        return False
    if log_action is not None:
        return log_action
    return logged_route and auto_action_logs_enabled()


async def open_action_log(
    action_name: str,
    params: dict[str, Any],
    *,
    summary: Optional[str] = None,
    logged_route: bool = True,
    log_action: Optional[bool] = None,
) -> Optional[str]:
    """Show the call as running, and return the block id that will close it.

    Args:
        action_name: The action being dispatched; the block's name.
        params: The action's input, shown as the block's input.
        summary: The caller's own description of the call, used as the block's display title.
            Without one the platform falls back to the action's configured display name.
        logged_route: Whether the route this call took is one the SDK logs by default. False
            for an in-process call on the worker that already owns the action — plumbing, not a
            tool call the user is waiting on. A default, not a veto: ``log_action`` overrides it.
        log_action: An explicit per-call override, winning over every other consideration
            except the non-loggable actions, which are a correctness rule.

    Returns:
        The block id, or ``None`` when this call is not logged **or the opening emit did not
        land** — so a block that never appeared is never closed. Hand it to
        :func:`close_action_log` or :func:`fail_action_log`.

    Never raises. Logging is telemetry wrapped around somebody's real work, and a failure to
    describe that work must not become a failure to do it.
    """
    if not _should_log(action_name, log_action, logged_route):
        return None
    try:
        block_id, result = await _emit_tool_use_block(action_name, display_title=summary, input=params, auto=True)
    except Exception as exc:
        logger.warning("could not open the action log", action_name=action_name, error=repr(exc))
        return None
    if not result.ok:
        # An emit reports a delivery failure as a value rather than raising, so this is the
        # only place it shows. Returning None keeps the pair honest: if the opening block
        # never reached the message, a closing one would render as a result with nothing
        # above it.
        logger.warning(
            "the action log did not open; not closing it either",
            action_name=action_name,
            error=result.error,
        )
        return None
    return block_id


async def close_action_log(
    block_id: Optional[str],
    action_name: str,
    result: Any,
    *,
    envelope: bool = False,
) -> None:
    """Complete the call's block with what the action returned. Never raises.

    ``envelope`` says the value came back wrapped by the gateway. The caller knows which route
    it took, so it is told rather than guessed at — a result is not inspected to see whether it
    *looks* like an envelope, which would mistake an action whose own output happens to carry
    those keys.
    """
    await _close(block_id, action_name, unwrap_result(result) if envelope else result)


def unwrap_result(result: Any) -> Any:
    """What the action actually answered, with the gateway's transport envelope taken off.

    Only ever called for a gateway result, which comes back as
    ``{"id", "status", "result", "error"}``. The id and status describe the delivery rather than
    the answer, and showing them buries the answer under two lines of plumbing. The API path
    already returns the inner value, so stripping it here makes the two routes display alike.

    The key check is a guard, not the decision — the route already settled that. It is here so
    a gateway response that is not shaped as expected is passed through whole rather than
    silently reduced to nothing.

    A failed call shows its ``error``, because the gateway reports failure as a *value* — it
    returns ``status="FAILED", result=None`` instead of raising, so this runs on the success
    path and reading ``result`` alone would show ``None`` and lose the reason.

    Anything that is not an envelope is returned untouched, which covers the API route and every
    action that simply returns a value.
    """
    if not isinstance(result, dict) or not ACTION_ENVELOPE_KEYS.issubset(result):
        return result
    return result.get("error") or result["result"]


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
