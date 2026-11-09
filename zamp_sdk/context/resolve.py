from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

from zamp_sdk.context.channel_context import ChannelContext, current_channel_context
from zamp_sdk.context.constants import EVAL_TRIAL_ID_FIELD, MOCK_CASE_ID_FIELD
from zamp_sdk.context.env import (
    ENV_BRANCH_ID,
    ENV_CHANNEL_ID,
    ENV_CHANNEL_TYPE,
    ENV_DB_BRANCH_MODE,
    ENV_ENVIRONMENT,
    ENV_EVAL_TRIAL_ID,
    ENV_MESSAGE_ID,
    ENV_MOCK_CASE_ID,
    ENV_RUN_ID,
    ENV_STREAMING_ID,
    ENV_TOOL_CALL_ID,
    ENV_TOOL_EXECUTION_MODE,
)
from zamp_sdk.context.execution_host import ExecutionHost, current_execution_host

_mock_case_withheld: ContextVar[bool] = ContextVar("zamp_mock_case_withheld", default=False)


def resolve_context() -> dict[str, Any]:
    ctx = {
        "channel_type": os.environ.get(ENV_CHANNEL_TYPE),
        "channel_id": os.environ.get(ENV_CHANNEL_ID),
        "streaming_id": os.environ.get(ENV_STREAMING_ID),
        "message_id": os.environ.get(ENV_MESSAGE_ID),
        "tool_call_id": os.environ.get(ENV_TOOL_CALL_ID),
        "run_id": os.environ.get(ENV_RUN_ID),
        "tool_execution_mode": os.environ.get(ENV_TOOL_EXECUTION_MODE),
    }
    return {k: v for k, v in ctx.items() if v}


def current_branch_context() -> dict[str, str]:
    if not os.environ.get(ENV_BRANCH_ID):
        return {}
    ctx = {
        "branch_id": os.environ.get(ENV_BRANCH_ID),
        "db_branch_mode": os.environ.get(ENV_DB_BRANCH_MODE),
        "environment": os.environ.get(ENV_ENVIRONMENT),
    }
    return {k: v for k, v in ctx.items() if v}


def current_eval_trial_id() -> str | None:
    return _current_run_value(ENV_EVAL_TRIAL_ID, EVAL_TRIAL_ID_FIELD)


def current_mock_case_id() -> str | None:
    if _mock_case_withheld.get():
        return None

    return _current_run_value(ENV_MOCK_CASE_ID, MOCK_CASE_ID_FIELD)


@contextmanager
def without_mock_case() -> Iterator[None]:
    token = _mock_case_withheld.set(True)
    try:
        yield
    finally:
        _mock_case_withheld.reset(token)


def _current_run_value(env_name: str, context_field: str) -> str | None:
    if current_execution_host() is not ExecutionHost.ACTIONS_HUB:
        return os.environ.get(env_name) or None

    from zamp_public_workflow_sdk.actions_hub.utils.context_utils import get_variable_from_context

    # The executor's metadata interceptor binds each field flat in the context, not nested under a key.
    return get_variable_from_context(context_field) or None


def resolve_channel_context() -> Optional[ChannelContext]:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        return current_channel_context()
    try:
        return ChannelContext(**resolve_context())
    except Exception:
        return None
