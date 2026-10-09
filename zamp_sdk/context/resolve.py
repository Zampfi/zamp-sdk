from __future__ import annotations

import os
from typing import Any, Optional

from zamp_sdk.context.channel_context import ChannelContext, current_channel_context
from zamp_sdk.context.env import (
    ENV_BRANCH_ID,
    ENV_CHANNEL_ID,
    ENV_CHANNEL_TYPE,
    ENV_DB_BRANCH_MODE,
    ENV_ENVIRONMENT,
    ENV_EVAL_TRIAL_ID,
    ENV_MESSAGE_ID,
    ENV_RUN_ID,
    ENV_STREAMING_ID,
    ENV_TOOL_CALL_ID,
    ENV_TOOL_EXECUTION_MODE,
)
from zamp_sdk.context.execution_host import ExecutionHost, current_execution_host

# zamp-executor binds the whole metadata context under this one key (its ZAMP_METADATA_CONTEXT_KEY).
_BOUND_METADATA_CONTEXT_KEY = "zamp_metadata_context"


def resolve_context() -> dict[str, Any]:
    """Read the agent context the runtime injected into the environment.

    Only keys that are actually set are returned, so an unset variable never
    overwrites context the server already holds. Shared by every SDK feature
    that attaches output to the running agent.
    """
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
    """The branch this process runs in, as injected by the runtime: ``branch_id`` plus its
    ``db_branch_mode`` and resource ``environment``, each present only when set.

    Empty unless a branch is set: mode and environment only mean something inside one.

    Env-only on purpose: in-process (``ACTIONS_HUB``) callers already run under a workflow
    whose metadata context carries the branch, so there is nothing to forward from here.
    """
    if not os.environ.get(ENV_BRANCH_ID):
        return {}
    ctx = {
        "branch_id": os.environ.get(ENV_BRANCH_ID),
        "db_branch_mode": os.environ.get(ENV_DB_BRANCH_MODE),
        "environment": os.environ.get(ENV_ENVIRONMENT),
    }
    return {k: v for k, v in ctx.items() if v}


def current_eval_trial_id() -> str | None:
    if current_execution_host() is not ExecutionHost.ACTIONS_HUB:
        return os.environ.get(ENV_EVAL_TRIAL_ID) or None

    from zamp_public_workflow_sdk.actions_hub.models.common_models import ZampMetadataContext
    from zamp_public_workflow_sdk.actions_hub.utils.context_utils import get_variable_from_context

    metadata = get_variable_from_context(_BOUND_METADATA_CONTEXT_KEY)
    if metadata is None:
        return None

    return ZampMetadataContext.model_validate(metadata).eval_trial_id


def resolve_channel_context() -> Optional[ChannelContext]:
    """The caller's full channel context as a validated ``ChannelContext``, or None.

    The execution host decides the source, the same fact that decides how actions
    dispatch: an ``ACTIONS_HUB`` host has a workflow that bound the context in-process,
    while an ``API`` host is a standalone process the runtime fed through ``ZAMP_*``
    environment variables. Sent once when calling the platform so actions don't each have
    to attach it.

    Deciding by host rather than by trying both matters on the API path: code running in a
    sandbox can import and call :func:`bind_channel_context` itself, and a bound value is
    never consulted there, so it cannot redirect its own output to a channel the runtime
    did not give it.

    Resolving the context is best-effort and must never break the action call it
    decorates, so *any* failure here resolves to None and the action goes through
    without a context.
    """
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        return current_channel_context()
    try:
        return ChannelContext(**resolve_context())
    except Exception:
        return None
