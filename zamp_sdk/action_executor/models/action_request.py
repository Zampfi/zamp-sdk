"""One action call, as the thing being dispatched rather than a list of arguments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from zamp_sdk.action_executor.execution_mode import ExecutionMode
from zamp_sdk.action_executor.models.retry_policy import RetryPolicy


@dataclass(frozen=True)
class ActionRequest:
    """Everything one ``ActionExecutor.execute`` call was asked to do.

    Built once and passed whole, so a route helper takes one argument and reads the fields it
    needs. Each route needs a different subset — the gateway needs no credentials, a local call
    needs the execution mode — and handing every route the union of them as keyword arguments
    was what made the dispatcher thirteen parameters wide.

    A dataclass, not a Pydantic model: it never crosses a boundary and is built on every action
    call, so there is nothing to validate and no reason to pay for it.
    """

    action_name: str
    params: dict[str, Any]
    base_url: Optional[str] = None
    auth_token: Optional[str] = None
    summary: Optional[str] = None
    return_type: Optional[type] = None
    execution_mode: Optional[ExecutionMode] = None
    action_retry_policy: Optional[RetryPolicy] = None
    action_start_to_close_timeout: Optional[timedelta] = None
    log_action: Optional[bool] = None
