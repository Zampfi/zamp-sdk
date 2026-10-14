"""A call the platform refuses for a rate limit raises ``RateLimitedError`` at once.

Two shapes, a **cross-repo contract** with pantheon: ``POST /actions`` answered 429, and a refusal
reported in-band as an ``error`` that starts with ``RATE_LIMITED:`` (``register_agent_task``
returns one for a refused agent task, and the executor callback a FAILED envelope with one). The
texts below are pantheon's current wording. The SDK never retries a refused call, and polling
``GET /actions/{id}`` is untouched: the platform never limits it.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from zamp_sdk import RateLimitedError
from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.models import ActionRequest, SdkConfig
from zamp_sdk.action_executor.utils import HttpClientError

_MODULE = "zamp_sdk.action_executor.action_executor"
_CONFIG = SdkConfig(base_url="https://api.zamp.test", auth_token="tok")

_TASK_REFUSAL = (
    "RATE_LIMITED: this organization is creating agent tasks faster than its limit (150 per hour). "
    "This request was NOT started. Wait 24 s before retrying; do not retry in a loop or in parallel. "
    "Otherwise finish without it."
)
_ACTION_REFUSAL = (
    "RATE_LIMITED: this user or agent is using SDK actions faster than its limit (120 per minute). "
    "This request was NOT started. Wait 1 s before retrying; do not retry in a loop or in parallel. "
    "Otherwise finish without it."
)
_NEVER_FITS_REFUSAL = (
    "RATE_LIMITED: this organization is creating agent tasks faster than its limit (150 per hour). "
    "This request was NOT started. It cannot fit the current limit; do not retry. "
    "Otherwise finish without it."
)


def _http_refusal() -> RateLimitedError:
    return RateLimitedError(
        "Your organization is using SDK actions faster than its limit (120 per minute).",
        retry_after_seconds=1.0,
        url="https://api.zamp.test/actions",
    )


def _recognised_as_429(error: BaseException) -> bool:
    """How pantheon's agent prompts tell a script to recognise a raised 429, on any SDK version."""
    return getattr(error, "status_code", None) == 429 or str(error).startswith("HTTP 429 from ")


class _SpawnResult(BaseModel):
    """A caller's ``return_type`` for a spawned agent task, without an ``error`` field."""

    task_id: str | None = None


class _Output(BaseModel):
    """A caller's ``return_type`` for an action whose own output has a ``result``."""

    result: dict | None = None
    saved: bool = False


class _Envelope(BaseModel):
    """A ``return_type`` the gateway applied to its envelope."""

    id: str
    status: str
    result: dict | None = None
    error: str | None = None


class TestARefusedCreate:
    """``POST /actions`` answered 429: nothing was started, and the caller hears it at once."""

    async def test_is_raised_at_once_without_a_retry(self):
        client = AsyncMock()
        client.post.side_effect = _http_refusal()

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(RateLimitedError),
        ):
            await ActionExecutor._post_action(client, "/actions", {})

        client.post.assert_awaited_once()
        mock_sleep.assert_not_awaited()

    async def test_ends_the_call_before_any_poll(self):
        client = AsyncMock()
        client.post.side_effect = _http_refusal()

        with (
            patch(f"{_MODULE}.HttpClient", return_value=client),
            pytest.raises(RateLimitedError) as exc_info,
        ):
            await ActionExecutor._execute_action("do_thing", {}, config=_CONFIG)

        client.get.assert_not_awaited()
        assert exc_info.value.retry_after_seconds == 1.0
        assert _recognised_as_429(exc_info.value)
        assert str(exc_info.value).startswith("HTTP 429 from https://api.zamp.test/actions: ")


class TestPollingIsUnchanged:
    """``GET /actions/{id}`` is never rate limited, so the poll has no 429 handling of its own:
    a 429 there (a plain ``HttpClientError``) would end the poll at once, as any non-5xx error
    always has."""

    async def test_a_429_on_a_poll_propagates_without_a_retry(self):
        client = AsyncMock()
        client.get.side_effect = HttpClientError(
            "HTTP 429 from https://api.zamp.test/actions/action-1", status_code=429
        )

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(HttpClientError) as exc_info,
        ):
            await ActionExecutor._poll_action_result(client, "action-1")

        client.get.assert_awaited_once()
        assert exc_info.value.status_code == 429


class TestAnInBandRefusal:
    """A refused call that completed instead of failing over HTTP raises all the same."""

    async def test_a_refused_agent_task_over_the_api(self):
        client = AsyncMock()
        client.post.return_value = {"id": "wf-1"}
        client.get.return_value = {"status": "COMPLETED", "result": {"task_id": None, "error": _TASK_REFUSAL}}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=client),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RateLimitedError) as exc_info,
        ):
            await ActionExecutor._execute_action("ExecuteAgentTaskWorkflow", {}, config=_CONFIG)

        error = exc_info.value
        assert error.retry_after_seconds == 24.0
        assert error.message.startswith("this organization is creating agent tasks")
        assert error.url is None
        assert _recognised_as_429(error)
        # Reads as the platform's own string.
        assert str(error) == _TASK_REFUSAL

    async def test_is_read_before_a_return_type_could_drop_it(self):
        client = AsyncMock()
        client.post.return_value = {"id": "wf-2"}
        client.get.return_value = {"status": "COMPLETED", "result": {"task_id": None, "error": _TASK_REFUSAL}}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=client),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RateLimitedError),
        ):
            await ActionExecutor._execute_action(
                "ExecuteAgentTaskWorkflow", {}, config=_CONFIG, return_type=_SpawnResult
            )

    @pytest.mark.parametrize(
        ("envelope", "retry_after_seconds"),
        [
            ({"id": "wf-3", "status": "FAILED", "result": None, "error": _ACTION_REFUSAL}, 1.0),
            ({"id": "wf-4", "status": "COMPLETED", "result": {"task_id": None, "error": _TASK_REFUSAL}}, 24.0),
            (_Envelope(id="wf-5", status="FAILED", error=_ACTION_REFUSAL), 1.0),
            (_Envelope(id="wf-6", status="COMPLETED", result={"task_id": None, "error": _TASK_REFUSAL}), 24.0),
        ],
        ids=["failed-envelope", "refused-agent-task", "failed-envelope-model", "refused-agent-task-model"],
    )
    async def test_through_the_gateway_is_raised_and_logged_as_a_failure(self, envelope, retry_after_seconds):
        gateway = AsyncMock(return_value=envelope)
        request = ActionRequest(action_name="do_thing", params={})

        with (
            patch(f"{_MODULE}.open_action_log", new_callable=AsyncMock, return_value="block-1"),
            patch(f"{_MODULE}.close_action_log", new_callable=AsyncMock) as close,
            patch(f"{_MODULE}.fail_action_log", new_callable=AsyncMock) as fail,
            pytest.raises(RateLimitedError) as exc_info,
        ):
            await ActionExecutor._execute_via_gateway(request, gateway)

        assert exc_info.value.retry_after_seconds == retry_after_seconds
        fail.assert_awaited_once_with("block-1", "do_thing", exc_info.value)
        close.assert_not_awaited()

    async def test_on_the_local_route(self):
        fake_ah = MagicMock()
        fake_ah.execute_action = AsyncMock(return_value={"task_id": None, "error": _TASK_REFUSAL})

        with (
            patch.dict(
                sys.modules,
                {
                    "zamp_public_workflow_sdk": MagicMock(),
                    "zamp_public_workflow_sdk.actions_hub": MagicMock(ActionsHub=fake_ah),
                    "zamp_public_workflow_sdk.actions_hub.constants": MagicMock(),
                    "zamp_public_workflow_sdk.actions_hub.models": MagicMock(),
                    "zamp_public_workflow_sdk.actions_hub.models.core_models": MagicMock(),
                },
            ),
            pytest.raises(RateLimitedError),
        ):
            await ActionExecutor._execute_via_actions_hub(
                ActionRequest(action_name="ExecuteAgentTaskWorkflow", params={})
            )

    def test_that_names_no_wait_has_none(self):
        """The platform names no wait when the call can never fit the limit."""
        with pytest.raises(RateLimitedError) as exc_info:
            ActionExecutor._raise_in_band_refusal({"task_id": None, "error": _NEVER_FITS_REFUSAL})

        assert exc_info.value.retry_after_seconds is None
        assert exc_info.value.status_code == 429


class TestNotARefusal:
    @pytest.mark.parametrize(
        "result",
        [
            None,
            "boom",
            42,
            [_ACTION_REFUSAL],
            {"error": None},
            {"error": "statement 0 failed [sqlstate=23505]: duplicate key"},
            {"id": "wf-7", "status": "COMPLETED", "result": {"rows": []}, "error": None},
            {"id": "wf-8", "status": "FAILED", "result": None, "error": "permission denied"},
            # The prefix is the contract: the word anywhere else is not a refusal.
            {"error": "upstream said RATE_LIMITED: but this is a quote"},
            {"id": "wf-9", "status": "COMPLETED", "result": ["not", "a", "mapping"], "error": None},
            # Outside the gateway's envelope, a nested ``result`` is the action's own output.
            {"result": {"error": _TASK_REFUSAL}, "saved": True},
            _Output(result={"error": _TASK_REFUSAL}, saved=True),
            _SpawnResult(task_id="t-1"),
            _Envelope(id="wf-10", status="COMPLETED", result={"task_id": "t-2"}),
        ],
    )
    def test_is_returned_as_before(self, result):
        ActionExecutor._raise_in_band_refusal(result)

    async def test_a_completed_action_is_returned_unchanged(self):
        client = AsyncMock()
        client.post.return_value = {"id": "wf-11"}
        client.get.return_value = {"status": "COMPLETED", "result": {"task_id": "t-3", "error": None}}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=client),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await ActionExecutor._execute_action("ExecuteAgentTaskWorkflow", {}, config=_CONFIG)

        assert result == {"task_id": "t-3", "error": None}
