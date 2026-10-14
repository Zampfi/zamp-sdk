"""A rate-limit refusal, a **cross-repo contract** with pantheon. ``POST /actions`` answered 429
raises ``HttpClientError`` at once (only a 5xx is retried), polling ``GET /actions/{id}`` is
untouched (the platform never limits it), and a refusal reported in-band comes back as a result.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.models import SdkConfig
from zamp_sdk.action_executor.utils import HttpClientError

_MODULE = "zamp_sdk.action_executor.action_executor"
_CONFIG = SdkConfig(base_url="https://api.zamp.test", auth_token="tok")

_HTTP_REFUSAL_MESSAGE = (
    "Your organization is using SDK actions faster than its limit (120 per minute). This request was NOT "
    "started. Wait 2 s before retrying; do not retry in a loop or in parallel. If you need a higher limit, "
    "contact support."
)
_TASK_REFUSAL = (
    "RATE_LIMITED: this organization is creating agent tasks faster than its limit (150 per hour). "
    "This request was NOT started. Wait 24 s before retrying; do not retry in a loop or in parallel. "
    "Otherwise finish without it."
)


def _http_refusal() -> HttpClientError:
    return HttpClientError(
        f"HTTP 429 from https://api.zamp.test/actions: {_HTTP_REFUSAL_MESSAGE}",
        status_code=429,
    )


def _response(status: int, body: str) -> AsyncMock:
    response = AsyncMock()
    response.ok = status < 400
    response.status = status
    response.text = AsyncMock(return_value=body)
    return response


def _session_returning(response) -> AsyncMock:
    """A mocked ``aiohttp.ClientSession`` whose every request answers ``response``."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    return session


def _recognised_as_429(error: BaseException) -> bool:
    """How pantheon's agent prompts tell a script to recognise a raised 429."""
    return getattr(error, "status_code", None) == 429 or str(error).startswith("HTTP 429 from ")


class TestARefusedCreate:
    """``POST /actions`` answered 429: nothing was started, and the caller hears it at once."""

    async def test_is_raised_at_once_without_a_retry(self):
        client = AsyncMock()
        client.post.side_effect = _http_refusal()

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(HttpClientError),
        ):
            await ActionExecutor._post_action(client, "/actions", {})

        client.post.assert_awaited_once()
        mock_sleep.assert_not_awaited()

    async def test_ends_the_call_before_any_poll(self):
        """Through the real ``HttpClient``: one POST answered 429, then the platform's text."""
        session = _session_returning(_response(429, json.dumps({"message": _HTTP_REFUSAL_MESSAGE})))

        with (
            patch("aiohttp.ClientSession", return_value=session),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(HttpClientError) as exc_info,
        ):
            await ActionExecutor._execute_action("do_thing", {}, config=_CONFIG)

        assert [call.kwargs["method"] for call in session.request.call_args_list] == ["POST"]
        mock_sleep.assert_not_awaited()
        assert exc_info.value.status_code == 429
        assert _recognised_as_429(exc_info.value)
        assert str(exc_info.value) == f"HTTP 429 from https://api.zamp.test/actions: {_HTTP_REFUSAL_MESSAGE}"


class TestPollingIsUnchanged:
    """``GET /actions/{id}`` is never rate limited, so the poll has no 429 handling of its own:
    a 429 there would end the poll at once, as any non-5xx error always has."""

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
    async def test_a_refused_agent_task_is_returned_as_a_result(self):
        """The task completes with the refusal as its ``error``; the caller reads it there."""
        client = AsyncMock()
        client.post.return_value = {"id": "wf-1"}
        client.get.return_value = {"status": "COMPLETED", "result": {"task_id": None, "error": _TASK_REFUSAL}}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=client),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await ActionExecutor._execute_action("ExecuteAgentTaskWorkflow", {}, config=_CONFIG)

        assert result == {"task_id": None, "error": _TASK_REFUSAL}
