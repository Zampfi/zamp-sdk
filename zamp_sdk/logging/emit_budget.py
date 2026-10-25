"""How many emits this run may send to the platform, and when it stops sending.

Only the *send* is capped: the local log line is written regardless. The count lives in a
mutable holder in a ContextVar, so tasks gathered from the binding one spend the same budget.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.logger import get_logger
from zamp_sdk.logging.constants import DEFAULT_MAX_EMITS

logger = get_logger(__name__)


@dataclass
class _EmitBudget:
    limit: int
    sent: int = 0
    stopped: bool = False
    warned: bool = False


_budget: ContextVar[Optional[_EmitBudget]] = ContextVar("zamp_emit_budget", default=None)

# A sandbox script is one process per run and binds nothing, so the process is the run.
_PROCESS_BUDGET = _EmitBudget(DEFAULT_MAX_EMITS)


def bind_emit_budget(max_emits: int) -> None:
    """Give this run a fresh budget of ``max_emits``, from a host that owns the run's lifetime."""
    if max_emits <= 0:
        raise ValueError(f"max_emits must be positive, got {max_emits}")
    _budget.set(_EmitBudget(max_emits))


def _current() -> Optional[_EmitBudget]:
    """The bound budget; else the process one on the API host; else None (uncapped).

    A long-lived worker (ActionsHub, gateway) serves many runs, so one global would be shared
    across them.
    """
    bound = _budget.get()
    if bound is not None:
        return bound
    return _PROCESS_BUDGET if current_execution_host() is ExecutionHost.API else None


def _warn_once(budget: _EmitBudget) -> None:
    if budget.warned:
        return
    budget.warned = True
    logger.warning(
        "no longer sending emit logs to the platform for this run; logging locally only",
        limit=budget.limit,
        sent=budget.sent,
    )


def try_spend_emit() -> bool:
    """Take one send from the budget; False once it is spent or sending was stopped."""
    budget = _current()
    if budget is None:
        return True
    if budget.stopped or budget.sent >= budget.limit:
        budget.stopped = True
        _warn_once(budget)
        return False
    # shortcut: no lock, so threads may overshoot the limit by a few under the GIL; fine for a cap.
    budget.sent += 1
    return True


def stop_emit_sending() -> None:
    """Stop sending for the rest of this run, e.g. after the platform refused an emit."""
    budget = _current()
    if budget is None:
        return
    budget.stopped = True
    _warn_once(budget)


def emit_sending_stopped() -> bool:
    budget = _current()
    return budget is not None and budget.stopped
