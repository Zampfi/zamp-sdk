import json
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import ToolApprovalRequired
from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import (
    SDK_TOOL_APPROVAL_EXIT_CODE,
    SDK_TOOL_APPROVAL_MARKER,
    TERMINAL_FAILURE_STATUSES,
    ActionStatus,
)
from zamp_sdk.action_executor.execution_mode import ExecutionMode
from zamp_sdk.action_executor.models import ActionRequest
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost

_MODULE = "zamp_sdk.action_executor.action_executor"
_POLICY_ID = "6f1c1c0e-0000-4000-8000-000000000001"
_BODY = {
    "id": "act-1",
    "status": "APPROVAL_REQUIRED",
    "result": None,
    "error": "needs approval",
    "policy_result_id": _POLICY_ID,
}


@pytest.fixture(params=["sandbox", "code_executor"])
def host(request, monkeypatch):
    if request.param == "code_executor":
        monkeypatch.setenv(ENV_EXECUTION_HOST, ExecutionHost.ACTIONS_HUB.value)
    else:
        monkeypatch.delenv(ENV_EXECUTION_HOST, raising=False)
    return request.param


def _assert_halted(host: str, raised: pytest.ExceptionInfo, capsys, action_name: str = "send_email") -> None:
    """Both hosts stop the caller; each in its own way, carrying the same two facts."""
    if host == "sandbox":
        assert raised.type is SystemExit
        assert raised.value.code == SDK_TOOL_APPROVAL_EXIT_CODE == 43
        line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(SDK_TOOL_APPROVAL_MARKER))
        payload = json.loads(line.removeprefix(SDK_TOOL_APPROVAL_MARKER + " "))
        assert payload == {"policy_result_id": _POLICY_ID, "action_name": action_name}
    else:
        assert raised.type is ToolApprovalRequired
        assert raised.value.policy_result_id == _POLICY_ID
        assert raised.value.action_name == action_name
        assert _POLICY_ID in str(raised.value) and action_name in str(raised.value)


def test_marker_and_exit_code_match_the_platform():
    assert SDK_TOOL_APPROVAL_MARKER == "__ZAMP_SDK_TOOL_APPROVAL__"
    assert SDK_TOOL_APPROVAL_EXIT_CODE == 43


def test_approval_required_is_neither_a_failure_nor_in_progress():
    assert ActionStatus.APPROVAL_REQUIRED == "APPROVAL_REQUIRED"
    assert ActionStatus.APPROVAL_REQUIRED not in TERMINAL_FAILURE_STATUSES


def test_tool_approval_required_is_not_an_exception():
    assert issubclass(ToolApprovalRequired, BaseException)
    assert not issubclass(ToolApprovalRequired, Exception)


def test_an_except_exception_does_not_swallow_the_halt():
    with pytest.raises(ToolApprovalRequired):
        try:
            raise ToolApprovalRequired(_POLICY_ID, "send_email")
        except Exception:  # noqa: BLE001 - the point of the test
            pytest.fail("except Exception caught the halt")


class TestInline:
    def test_halts(self, host, capsys):
        with pytest.raises(BaseException) as raised:
            ActionExecutor._result_or_raise(_BODY, "act-1", action_name="send_email")
        _assert_halted(host, raised, capsys)

    async def test_execute_inline_names_the_action(self, host, capsys):
        client = AsyncMock()
        client.post.return_value = _BODY
        with pytest.raises(BaseException) as raised:
            await ActionExecutor._execute_inline(client, {"action_name": "send_email"}, None)
        _assert_halted(host, raised, capsys)

    @pytest.mark.parametrize("status", ["FAILED", "WEIRD"])
    def test_other_statuses_are_unchanged(self, host, status):
        error = RuntimeError
        with pytest.raises(error, match="FAILED: bad|unexpected status: WEIRD"):
            ActionExecutor._result_or_raise({"status": status, "error": "bad"}, "x")

    def test_completed_is_unchanged(self, host):
        assert ActionExecutor._result_or_raise({"status": "COMPLETED", "result": 7}, "x") == 7


class TestPoll:
    @staticmethod
    async def _poll(*bodies):
        client = AsyncMock()
        client.get.side_effect = list(bodies)
        with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock):
            return await ActionExecutor._poll_action_result(client, "act-1", action_name="send_email")

    async def test_halts(self, host, capsys):
        with pytest.raises(BaseException) as raised:
            await self._poll({"status": "RUNNING"}, _BODY)
        _assert_halted(host, raised, capsys)

    async def test_unknown_status_still_raises(self, host):
        with pytest.raises(RuntimeError, match="unexpected status: WEIRD"):
            await self._poll({"status": "WEIRD"})

    async def test_completed_and_failed_are_unchanged(self, host):
        assert await self._poll({"status": "COMPLETED", "result": 3}) == 3
        with pytest.raises(RuntimeError, match="FAILED.*boom"):
            await self._poll({"status": "FAILED", "error": "boom"})


class TestGateway:
    @staticmethod
    async def _run(envelope):
        request = ActionRequest(action_name="send_email", params={})
        return await ActionExecutor._execute_via_gateway(request, AsyncMock(return_value=envelope))

    async def test_halts(self, host, capsys):
        with pytest.raises(BaseException) as raised:
            await self._run(_BODY)
        _assert_halted(host, raised, capsys)

    async def test_completed_envelope_is_returned_untouched(self, host):
        envelope = {"id": "a", "status": "COMPLETED", "result": 1, "error": None}
        assert await self._run(envelope) == envelope

    async def test_failed_envelope_is_returned_untouched(self, host):
        envelope = {"id": "a", "status": "FAILED", "result": None, "error": "bad"}
        assert await self._run(envelope) == envelope

    async def test_a_result_that_merely_has_a_status_key_is_left_alone(self, host):
        value = {"status": "APPROVAL_REQUIRED"}
        assert await self._run(value) == value


class TestApi:
    """End to end through ``execute`` on the API route, which only a sandbox script takes."""

    @pytest.mark.parametrize("mode", [ExecutionMode.INLINE, None])
    async def test_halts_through_execute(self, capsys, mode, monkeypatch):
        monkeypatch.delenv(ENV_EXECUTION_HOST, raising=False)
        monkeypatch.setenv("ZAMP_BASE_URL", "https://x")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "t")
        client = AsyncMock()
        client.post.return_value = _BODY if mode else {"id": "act-1"}
        client.get.return_value = _BODY
        with (
            patch(f"{_MODULE}.HttpClient", return_value=client),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(BaseException) as raised,
        ):
            await ActionExecutor.execute("send_email", {}, execution_mode=mode)
        _assert_halted("sandbox", raised, capsys)
