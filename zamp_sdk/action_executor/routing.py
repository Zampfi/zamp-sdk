"""Where an action call is dispatched, and how that is decided."""

from __future__ import annotations

from typing import Any, Callable

from zamp_sdk.action_executor.constants import Route
from zamp_sdk.context import ExecutionHost, current_execution_host


def get_action_gateway() -> Callable[..., Any] | None:
    """The action gateway registered on ActionsHub, or None if none is."""
    from zamp_public_workflow_sdk.actions_hub import ActionsHub

    return ActionsHub.get_action_gateway()


async def is_registered_locally(action_name: str) -> bool:
    """Whether the action resolves to one registered in this environment."""
    from zamp_public_workflow_sdk.actions_hub import ActionsHub
    from zamp_public_workflow_sdk.actions_hub.models.core_models import ActionFilter

    actions = await ActionsHub.get_available_actions(ActionFilter(name=action_name))
    return len(actions) > 0


async def resolve_route(action_name: str) -> tuple[Route, Callable[..., Any] | None]:
    """Which of the three paths this action takes, and the gateway if it needs one."""
    if current_execution_host() is not ExecutionHost.ACTIONS_HUB:
        return Route.API, None
    gateway = get_action_gateway()
    if gateway is not None and not await is_registered_locally(action_name):
        return Route.GATEWAY, gateway
    return Route.LOCAL_AH, None
