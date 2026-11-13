"""On the code-executor host a halt is recorded as well as raised, so authored code that loses the
exception (task group, gather, a dropped task) cannot make the phase carry on."""

import asyncio
import contextvars
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from conftest import drained_steps
from zamp_sdk import ToolApprovalRequired
from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import Route
from zamp_sdk.action_executor.models import ActionRequest
from zamp_sdk.action_executor.utils import pending_tool_approval, start_tool_approval_tracking
from zamp_sdk.capture import start_log_capture
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost

_MODULE = "zamp_sdk.action_executor.action_executor"
_POLICY_ID = "6f1c1c0e-0000-4000-8000-000000000001"
_ENVELOPE = {
    "id": "act-1",
    "status": "APPROVAL_REQUIRED",
    "result": None,
    "error": "needs approval",
    "policy_result_id": _POLICY_ID,
}


@pytest.fixture(autouse=True)
def code_executor_host(monkeypatch):
    monkeypatch.setenv(ENV_EXECUTION_HOST, ExecutionHost.ACTIONS_HUB.value)
    start_tool_approval_tracking()


def _call(name: str = "send_email"):
    return ActionExecutor._halt_for_tool_approval(_ENVELOPE, "act-1", name)


async def _halting_call(name: str = "send_email") -> None:
    await asyncio.sleep(0)
    _call(name)


def _assert_recorded(name: str = "send_email") -> None:
    halt = pending_tool_approval()
    assert halt is not None
    assert (halt.policy_result_id, halt.action_name) == (_POLICY_ID, name)


def test_nothing_pending_before_a_halt():
    assert pending_tool_approval() is None


def test_nothing_is_recorded_when_tracking_was_not_started():
    def untracked():
        with pytest.raises(ToolApprovalRequired):
            _call()
        return pending_tool_approval()

    assert contextvars.Context().run(untracked) is None


def test_first_halt_wins():
    for name in ("first", "second"):
        with pytest.raises(ToolApprovalRequired):
            _call(name)
    _assert_recorded("first")


async def test_recorded_through_a_task_group():
    with pytest.raises(BaseExceptionGroup):
        async with asyncio.TaskGroup() as group:
            group.create_task(_halting_call())
    _assert_recorded()


async def test_recorded_when_gather_swallows_the_halt():
    results = await asyncio.gather(_halting_call(), return_exceptions=True)
    assert isinstance(results[0], ToolApprovalRequired)
    _assert_recorded()


async def test_recorded_from_a_task_nobody_awaits():
    task = asyncio.create_task(_halting_call())
    await asyncio.sleep(0.01)
    assert task.done()
    task.exception()  # retrieved so the loop does not warn about it
    _assert_recorded()


async def test_recorded_when_a_plain_except_swallows_it():
    try:
        await _halting_call()
    except BaseException:  # noqa: BLE001 - the authored code this guards against
        pass
    _assert_recorded()


class TestStepLog:
    async def test_halted_call_is_in_the_step_log(self):
        start_log_capture()
        gateway = AsyncMock(return_value=_ENVELOPE)
        with (
            pytest.raises(ToolApprovalRequired),
            _gateway(gateway),
        ):
            await ActionExecutor.execute("send_email", {"to": "a@b.c"})
        (step,) = drained_steps()
        assert step["name"] == "send_email"
        assert step["input"] == {"to": "a@b.c"}
        assert "needs approval" in step["error"]


class _Out(BaseModel):
    status: str


class TestGatewayWithReturnType:
    async def test_return_type_does_not_hide_the_halt(self):
        # A gateway that validates the envelope into the model would hide the status; the SDK
        # asks for the raw envelope and validates after the check.
        gateway = AsyncMock(return_value=_ENVELOPE)
        request = ActionRequest(action_name="send_email", params={}, return_type=_Out)
        with pytest.raises(ToolApprovalRequired):
            await ActionExecutor._execute_via_gateway(request, gateway)
        assert gateway.call_args.kwargs["return_type"] is None
        _assert_recorded()

    async def test_return_type_is_applied_to_a_normal_envelope(self):
        envelope = {"id": "a", "status": "COMPLETED", "result": 1, "error": None}
        gateway = AsyncMock(return_value=envelope)
        request = ActionRequest(action_name="x", params={}, return_type=_Out)
        assert await ActionExecutor._execute_via_gateway(request, gateway) == _Out(status="COMPLETED")


def _gateway(gateway):
    return patch(f"{_MODULE}.resolve_route", new=AsyncMock(return_value=(Route.GATEWAY, gateway)))
