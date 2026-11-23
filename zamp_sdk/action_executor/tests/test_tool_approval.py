import json
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import (
    SDK_TOOL_APPROVAL_EXIT_CODE,
    SDK_TOOL_APPROVAL_MARKER,
    TERMINAL_FAILURE_STATUSES,
    ActionStatus,
)
from zamp_sdk.action_executor.execution_mode import ExecutionMode
from zamp_sdk.action_executor.models import ActionRequest
from zamp_sdk.action_executor.utils import HttpClientError
from zamp_sdk.context import ENV_EXECUTION_HOST

_MODULE = "zamp_sdk.action_executor.action_executor"
_POLICY_ID = "6f1c1c0e-0000-4000-8000-000000000001"
_BODY = {
    "id": "act-1",
    "status": "APPROVAL_REQUIRED",
    "result": None,
    "error": None,
    "message": "send_email needs approval; the user has been asked",
    "policy_result_id": _POLICY_ID,
}


def _assert_halted(raised: pytest.ExceptionInfo, capsys, action_name: str = "send_email") -> None:
    """A sandbox script exits 43 after printing the marker line."""
    assert raised.type is SystemExit
    assert raised.value.code == SDK_TOOL_APPROVAL_EXIT_CODE == 43
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(SDK_TOOL_APPROVAL_MARKER))
    payload = json.loads(line.removeprefix(SDK_TOOL_APPROVAL_MARKER + " "))
    assert payload == {"policy_result_id": _POLICY_ID, "action_name": action_name}


@pytest.mark.parametrize("missing", [{}, {"policy_result_id": None}, {"policy_result_id": ""}])
class TestMissingPolicyResultId:
    """Nothing can approve such a response, so it is a plain error, not a halt."""

    _BAD = {"id": "act-9", "status": "APPROVAL_REQUIRED", "result": None, "error": "x"}

    def test_inline(self, missing):
        with pytest.raises(RuntimeError, match="Action act-9 APPROVAL_REQUIRED without a policy_result_id"):
            ActionExecutor._result_or_raise({**self._BAD, **missing}, "act-9", action_name="send_email")

    async def test_poll(self, missing):
        client = AsyncMock()
        client.get.return_value = {**self._BAD, **missing}
        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="Action act-9 APPROVAL_REQUIRED without a policy_result_id"),
        ):
            await ActionExecutor._poll_action_result(client, "act-9", action_name="send_email")


def test_marker_and_exit_code_match_the_platform():
    assert SDK_TOOL_APPROVAL_MARKER == "__ZAMP_SDK_TOOL_APPROVAL__"
    assert SDK_TOOL_APPROVAL_EXIT_CODE == 43


def test_approval_required_is_neither_a_failure_nor_in_progress():
    assert ActionStatus.APPROVAL_REQUIRED == "APPROVAL_REQUIRED"
    assert ActionStatus.APPROVAL_REQUIRED not in TERMINAL_FAILURE_STATUSES


class TestInline:
    def test_halts(self, capsys):
        with pytest.raises(BaseException) as raised:
            ActionExecutor._result_or_raise(_BODY, "act-1", action_name="send_email")
        _assert_halted(raised, capsys)

    async def test_execute_inline_names_the_action(self, capsys):
        client = AsyncMock()
        client.post.return_value = _BODY
        with pytest.raises(BaseException) as raised:
            await ActionExecutor._execute_inline(client, {"action_name": "send_email"}, None)
        _assert_halted(raised, capsys)

    @pytest.mark.parametrize("status", ["FAILED", "WEIRD"])
    def test_other_statuses_are_unchanged(self, status):
        error = RuntimeError
        with pytest.raises(error, match="FAILED: bad|unexpected status: WEIRD"):
            ActionExecutor._result_or_raise({"status": status, "error": "bad"}, "x")

    def test_completed_is_unchanged(self):
        assert ActionExecutor._result_or_raise({"status": "COMPLETED", "result": 7}, "x") == 7


class TestPoll:
    @staticmethod
    async def _poll(*bodies):
        client = AsyncMock()
        client.get.side_effect = list(bodies)
        with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock):
            return await ActionExecutor._poll_action_result(client, "act-1", action_name="send_email")

    async def test_halts(self, capsys):
        with pytest.raises(BaseException) as raised:
            await self._poll({"status": "RUNNING"}, _BODY)
        _assert_halted(raised, capsys)

    async def test_unknown_status_still_raises(self):
        with pytest.raises(RuntimeError, match="unexpected status: WEIRD"):
            await self._poll({"status": "WEIRD"})

    async def test_completed_and_failed_are_unchanged(self):
        assert await self._poll({"status": "COMPLETED", "result": 3}) == 3
        with pytest.raises(RuntimeError, match="FAILED.*boom"):
            await self._poll({"status": "FAILED", "error": "boom"})


class TestGateway:
    @staticmethod
    async def _run(envelope):
        request = ActionRequest(action_name="send_email", params={})
        return await ActionExecutor._execute_via_gateway(request, AsyncMock(return_value=envelope))

    async def test_completed_envelope_is_returned_untouched(self):
        envelope = {"id": "a", "status": "COMPLETED", "result": 1, "error": None}
        assert await self._run(envelope) == envelope

    async def test_failed_envelope_is_returned_untouched(self):
        envelope = {"id": "a", "status": "FAILED", "result": None, "error": "bad"}
        assert await self._run(envelope) == envelope

    async def test_an_approval_envelope_is_returned_untouched(self):
        assert await self._run(_BODY) == _BODY


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
        _assert_halted(raised, capsys)


def _transport(responses: dict[tuple[str, str], tuple[int, dict]]):
    """A stand-in for ``aiohttp.ClientSession`` so the REAL ``HttpClient`` parses each response."""

    def _session(*_args, **_kwargs):
        def _request(method, url, **_kw):
            status, body = responses[(method, url.removeprefix("https://api.zamp.test"))]
            response = AsyncMock()
            response.ok = 200 <= status < 300
            response.status = status
            response.text = AsyncMock(return_value=json.dumps(body))
            ctx = AsyncMock()
            ctx.__aenter__.return_value = response
            ctx.__aexit__.return_value = False
            return ctx

        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = False
        session.request = _request
        return session

    return patch("aiohttp.ClientSession", side_effect=_session)


@pytest.mark.parametrize("mode", [ExecutionMode.INLINE, ExecutionMode.DURABLE])
class TestThroughRealHttpClient:
    """The platform answers APPROVAL_REQUIRED as a normal 200 body with ``error: null``."""

    async def _run(self, mode, responses):
        config = type("Cfg", (), {"base_url": "https://api.zamp.test", "auth_token": "t"})()
        with _transport(responses), patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock):
            await ActionExecutor._execute_action("send_email", {}, config=config, execution_mode=mode)

    def _responses(self, mode):
        if mode is ExecutionMode.INLINE:
            return {("POST", "/actions"): (200, _BODY)}
        return {
            ("POST", "/actions"): (200, {"id": "act-1", "status": "PENDING", "result": None, "error": None}),
            ("GET", "/actions/act-1"): (200, _BODY),
        }

    async def test_halts(self, mode, capsys):
        with pytest.raises((SystemExit, RuntimeError)) as raised:
            await self._run(mode, self._responses(mode))
        _assert_halted(raised, capsys)

    async def test_missing_policy_result_id_is_runtime_error(self, mode):
        bad = {k: v for k, v in _BODY.items() if k != "policy_result_id"}
        responses = self._responses(mode)
        responses[("POST", "/actions") if mode is ExecutionMode.INLINE else ("GET", "/actions/act-1")] = (200, bad)
        with pytest.raises(RuntimeError, match="APPROVAL_REQUIRED without a policy_result_id"):
            await self._run(mode, responses)

    async def test_failed_body_still_raises_http_client_error(self, mode):
        failed = {"id": "act-1", "status": "FAILED", "result": None, "error": "boom"}
        responses = self._responses(mode)
        responses[("POST", "/actions") if mode is ExecutionMode.INLINE else ("GET", "/actions/act-1")] = (200, failed)
        with pytest.raises(HttpClientError, match="boom"):
            await self._run(mode, responses)
