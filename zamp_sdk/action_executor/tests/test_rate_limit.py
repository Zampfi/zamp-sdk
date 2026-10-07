"""Recognising a rate-limit refusal in whatever an action call returned or raised.

The in-band shapes are a **cross-repo contract** with pantheon: ``register_agent_task`` returns
``error="RATE_LIMITED: ..."`` (the spawned agent task completes), and the executor callback turns
a refusal into a FAILED envelope with that error. The prefix is the contract; the texts below are
pantheon's current wording, which this side reads tolerantly.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from zamp_sdk import AgentDbError, RateLimitedError, rate_limit_refusal
from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.models import SdkConfig
from zamp_sdk.action_executor.utils import HttpClient, HttpClientError

_TASK_REFUSAL = (
    "RATE_LIMITED: this organization is creating agent tasks faster than its limit (150 per hour). "
    "No task was created. Wait 24 s before retrying; do not retry in a loop or in parallel. "
    "Otherwise finish without it."
)
_ACTION_REFUSAL = (
    "RATE_LIMITED: this user or agent is using SDK actions faster than its limit (120 per minute). "
    "This request was NOT started. Wait 1 s before retrying; do not retry in a loop or in parallel. "
    "Otherwise finish without it."
)


class _SpawnResult(BaseModel):
    """A caller's ``return_type`` for a spawned agent task, keeping the optional ``error``."""

    task_id: str | None = None
    error: str | None = None


class _Envelope(BaseModel):
    """A caller's ``return_type`` for a code-executor envelope."""

    id: str
    status: str
    result: _SpawnResult | None = None
    error: str | None = None


class TestInBandShapes:
    def test_a_refused_agent_task_result(self):
        """``ExecuteAgentTaskWorkflow`` over the API: a COMPLETED action whose result carries it."""
        refusal = rate_limit_refusal({"output": None, "task_id": None, "status": None, "error": _TASK_REFUSAL})

        assert isinstance(refusal, RateLimitedError)
        assert refusal.retry_after == 24.0
        assert refusal.status_code is None
        assert refusal.message.startswith("this organization is creating agent tasks")
        # Reads back as the platform's own string.
        assert str(refusal) == _TASK_REFUSAL

    def test_a_refused_call_in_the_code_executor(self):
        envelope = {"id": "wf-1", "status": "FAILED", "result": None, "error": _ACTION_REFUSAL}

        refusal = rate_limit_refusal(envelope)

        assert refusal is not None
        assert refusal.retry_after == 1.0

    def test_a_refused_agent_task_in_the_code_executor(self):
        envelope = {"id": "wf-2", "status": "COMPLETED", "result": {"task_id": None, "error": _TASK_REFUSAL}}

        assert rate_limit_refusal(envelope) is not None

    def test_the_error_string_itself(self):
        assert rate_limit_refusal(_ACTION_REFUSAL) is not None

    def test_a_wait_in_other_wording_is_still_read(self):
        refusal = rate_limit_refusal("RATE_LIMITED: limit reached. Do not retry in a loop; retry after 24 s.")

        assert refusal is not None
        assert refusal.retry_after == 24.0

    def test_text_that_names_no_wait_has_none(self):
        refusal = rate_limit_refusal("RATE_LIMITED: it cannot fit the current limit; do not retry.")

        assert refusal is not None
        assert refusal.retry_after is None


class TestValidatedShapes:
    """A ``return_type`` turns the result into a model; a model that keeps ``error`` still shows it."""

    def test_a_refused_agent_task_result_validated_into_a_model(self):
        refusal = rate_limit_refusal(_SpawnResult(error=_TASK_REFUSAL))

        assert refusal is not None
        assert refusal.retry_after == 24.0

    def test_a_refused_call_in_an_envelope_model(self):
        envelope = _Envelope(id="wf-1", status="FAILED", error=_ACTION_REFUSAL)

        refusal = rate_limit_refusal(envelope)

        assert refusal is not None
        assert refusal.retry_after == 1.0

    def test_a_refused_agent_task_nested_in_an_envelope_model(self):
        envelope = _Envelope(id="wf-2", status="COMPLETED", result=_SpawnResult(error=_TASK_REFUSAL))

        assert rate_limit_refusal(envelope) is not None


class TestRaisedShapes:
    def test_an_http_refusal_is_returned_as_it_is(self):
        error = RateLimitedError("over the limit", retry_after=2.0, check="org", limit_class="sdk.action")

        assert rate_limit_refusal(error) is error

    def test_a_terminal_status_raised_by_the_poll(self):
        """The poll raises a terminal status as ``Action <id> <status>: <error>``."""
        refusal = rate_limit_refusal(RuntimeError(f"Action wf-3 FAILED: {_ACTION_REFUSAL}"))

        assert refusal is not None
        assert refusal.retry_after == 1.0

    async def test_a_failed_action_over_the_api(self):
        """Over the API a failed action's poll is a 200 whose body carries the error, which the
        HTTP client raises as an ``HttpClientError`` with that error as its text."""
        body = json.dumps({"id": "wf-3", "status": "FAILED", "result": None, "error": _ACTION_REFUSAL})
        response = AsyncMock(ok=True, status=200, headers={})
        response.text = AsyncMock(return_value=body)
        request = AsyncMock()
        request.__aenter__ = AsyncMock(return_value=response)
        request.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.request = MagicMock(return_value=request)

        with (
            patch("aiohttp.ClientSession", return_value=session),
            patch("zamp_sdk.action_executor.action_executor.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(HttpClientError) as exc_info,
        ):
            await ActionExecutor._poll_action_result(HttpClient(base_url="https://api.zamp.test"), "wf-3")

        assert exc_info.value.status_code == 200
        refusal = rate_limit_refusal(exc_info.value)
        assert refusal is not None
        assert refusal.retry_after == 1.0

    def test_an_agent_db_error_from_a_failed_action_over_the_api(self):
        error = AgentDbError.from_exception(HttpClientError(_ACTION_REFUSAL, status_code=200))

        refusal = rate_limit_refusal(error)

        assert refusal is not None
        assert error.status_code is None

    def test_an_agent_db_error_over_a_429(self):
        cause = RateLimitedError("over the limit", retry_after=2.0, url="https://api.zamp.test/actions")
        try:
            raise AgentDbError.from_exception(cause) from cause
        except AgentDbError as error:
            assert rate_limit_refusal(error) is cause

    def test_an_agent_db_error_from_an_in_band_failure(self):
        error = AgentDbError.from_exception(RuntimeError(f"Action wf-4 FAILED: {_ACTION_REFUSAL}"))

        assert rate_limit_refusal(error) is not None


class TestNotARefusal:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "boom",
            42,
            ["RATE_LIMITED: in a list"],
            {"error": None},
            {"error": "statement 0 failed [sqlstate=23505]: duplicate key"},
            {"id": "wf-5", "status": "COMPLETED", "result": {"rows": []}, "error": None},
            {"id": "wf-6", "status": "FAILED", "result": None, "error": "permission denied"},
            # The prefix is the contract: the word anywhere else is not a refusal.
            {"error": "upstream said RATE_LIMITED: but this is a quote"},
            # A result that is not an envelope is not opened.
            {"result": {"error": _TASK_REFUSAL}},
            RuntimeError("Action wf-7 FAILED: boom"),
            AgentDbError("duplicate key", sqlstate="23505"),
            _SpawnResult(task_id="t-1"),
            _Envelope(id="wf-8", status="COMPLETED", result=_SpawnResult(task_id="t-2")),
        ],
    )
    def test_is_none(self, value):
        assert rate_limit_refusal(value) is None


class TestSuccessSemanticsAreUnchanged:
    """Finding a refusal is opt-in: the executor returns and raises exactly what it did before."""

    async def test_a_completed_action_carrying_a_refusal_is_returned_not_raised(self):
        result = {"task_id": None, "error": _TASK_REFUSAL}
        client = AsyncMock()
        client.get.return_value = {"status": "COMPLETED", "result": result}

        with patch("zamp_sdk.action_executor.action_executor.asyncio.sleep", new_callable=AsyncMock):
            returned = await ActionExecutor._poll_action_result(client, "wf-8")

        assert returned == result
        assert rate_limit_refusal(returned) is not None

    async def test_a_refusal_validated_into_a_return_type_is_returned_and_recognised(self):
        client = AsyncMock()
        client.post.return_value = {"id": "wf-10"}
        client.get.return_value = {"status": "COMPLETED", "result": {"task_id": None, "error": _TASK_REFUSAL}}

        with (
            patch("zamp_sdk.action_executor.action_executor.HttpClient", return_value=client),
            patch("zamp_sdk.action_executor.action_executor.asyncio.sleep", new_callable=AsyncMock),
        ):
            returned = await ActionExecutor._execute_action(
                "ExecuteAgentTaskWorkflow",
                {},
                config=SdkConfig(base_url="https://api.zamp.test", auth_token="tok"),
                return_type=_SpawnResult,
            )

        assert isinstance(returned, _SpawnResult)
        refusal = rate_limit_refusal(returned)
        assert refusal is not None
        assert refusal.retry_after == 24.0

    async def test_a_failed_action_carrying_a_refusal_still_raises_runtime_error(self):
        client = AsyncMock()
        client.get.return_value = {"status": "FAILED", "error": _ACTION_REFUSAL}

        with (
            patch("zamp_sdk.action_executor.action_executor.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError) as exc_info,
        ):
            await ActionExecutor._poll_action_result(client, "wf-9")

        assert type(exc_info.value) is RuntimeError
        assert rate_limit_refusal(exc_info.value) is not None
