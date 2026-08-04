import json
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.execution_mode import ExecutionMode
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig
from zamp_sdk.action_executor.utils import HttpClientError
from zamp_sdk.capture import drain_log_capture, start_log_capture

_MODULE = "zamp_sdk.action_executor.action_executor"
# The API path is the default, so reaching it needs no host declaration.
_API_ENV: dict[str, str] = {}
_HUB_ENV = {"ZAMP_SDK_EXECUTION_HOST": "actions_hub"}


def _http_error(status_code: int) -> HttpClientError:
    return HttpClientError(f"HTTP {status_code}", status_code=status_code, response_body="boom")


class TestExecute:
    """Tests for the public ActionExecutor.execute() entry point (sandbox path)."""

    async def test_explicit_config_forwarded(self, base_url, auth_token):
        with (
            patch.dict("os.environ", _API_ENV, clear=False),
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock,
        ):
            mock.return_value = {"result": "ok"}

            result = await ActionExecutor.execute(
                "send_invoice",
                {"id": "inv_1"},
                base_url=base_url,
                auth_token=auth_token,
            )

            assert result == {"result": "ok"}
            call_kwargs = mock.call_args.kwargs
            config = call_kwargs["config"]
            assert isinstance(config, SdkConfig)
            assert config.base_url == base_url
            assert config.auth_token == auth_token

    async def test_falls_back_to_env_vars(self, base_url, auth_token):
        env = {"ZAMP_BASE_URL": base_url, "ZAMP_AUTH_TOKEN": auth_token, **_API_ENV}
        with (
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock,
            patch.dict("os.environ", env, clear=False),
        ):
            mock.return_value = "done"
            result = await ActionExecutor.execute("my_action", {"k": "v"})

            assert result == "done"
            mock.assert_awaited_once()
            config = mock.call_args.kwargs["config"]
            assert config.base_url == base_url
            assert config.auth_token == auth_token

    async def test_raises_when_env_vars_missing(self):
        with (
            patch.dict("os.environ", _API_ENV, clear=True),
            pytest.raises(KeyError, match="ZAMP_BASE_URL"),
        ):
            await ActionExecutor.execute("action", {})

    async def test_forwards_all_params(self, base_url, auth_token):
        retry = RetryPolicy.default()
        timeout = timedelta(minutes=5)

        with (
            patch.dict("os.environ", _API_ENV, clear=False),
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock,
        ):
            mock.return_value = None

            await ActionExecutor.execute(
                "action",
                {"x": 1},
                base_url=base_url,
                auth_token=auth_token,
                summary="test summary",
                return_type=dict,
                action_retry_policy=retry,
                action_start_to_close_timeout=timeout,
            )

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["summary"] == "test summary"
            assert call_kwargs["return_type"] is dict
            assert call_kwargs["action_retry_policy"] is retry
            assert call_kwargs["action_start_to_close_timeout"] == timeout

    async def test_returns_result(self, base_url, auth_token):
        with (
            patch.dict("os.environ", _API_ENV, clear=False),
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock,
        ):
            mock.return_value = {"amount": 42}

            result = await ActionExecutor.execute(
                "calc",
                {},
                base_url=base_url,
                auth_token=auth_token,
            )

            assert result == {"amount": 42}


class TestExecuteDispatch:
    """Tests for the api-vs-actions-hub dispatch in ActionExecutor.execute().

    The API path is the default so an SDK used outside Zamp's own runtimes works with no
    configuration; a host providing an ActionsHub opts in via ZAMP_SDK_EXECUTION_HOST.
    """

    async def test_unconfigured_env_takes_http_path(self, base_url, auth_token):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api_mock,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            api_mock.return_value = "api-result"

            result = await ActionExecutor.execute(
                "action",
                {},
                base_url=base_url,
                auth_token=auth_token,
                execution_mode=ExecutionMode.SYNC,
            )

            assert result == "api-result"
            api_mock.assert_awaited_once()
            ah_mock.assert_not_called()
            kwargs = api_mock.call_args.kwargs
            assert kwargs["base_url"] == base_url
            assert kwargs["auth_token"] == auth_token

    async def test_declared_hub_uses_actions_hub_path(self, base_url, auth_token):
        with (
            patch.dict("os.environ", _HUB_ENV, clear=True),
            patch.object(ActionExecutor, "_get_action_gateway", return_value=None),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api_mock,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            ah_mock.return_value = "hub-result"

            result = await ActionExecutor.execute(
                "action",
                {"p": 1},
                execution_mode=ExecutionMode.ASYNC,
            )

            assert result == "hub-result"
            ah_mock.assert_awaited_once()
            api_mock.assert_not_called()
            kwargs = ah_mock.call_args.kwargs
            assert kwargs["execution_mode"] is ExecutionMode.ASYNC

    async def test_a_stray_legacy_inside_sandbox_var_changes_nothing(self):
        """The SDK no longer reads INSIDE_SANDBOX anywhere. A runtime that still injects it
        (the sandbox image does) must reach the API path by being unconfigured, exactly like
        any other caller — not by that variable being honoured."""
        with (
            patch.dict("os.environ", {"INSIDE_SANDBOX": "true"}, clear=True),
            patch.object(ActionExecutor, "_get_action_gateway", return_value=None),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api_mock,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            api_mock.return_value = "api"

            await ActionExecutor.execute("action", {})

            api_mock.assert_awaited_once()
            ah_mock.assert_not_called()

    @pytest.mark.parametrize("value", ["", "   ", "api", "API", " Api "])
    async def test_api_and_blank_values_take_the_http_path(self, value):
        with (
            patch.dict("os.environ", {"ZAMP_SDK_EXECUTION_HOST": value}, clear=True),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api_mock,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            api_mock.return_value = "api"

            await ActionExecutor.execute("action", {})

            api_mock.assert_awaited_once()
            ah_mock.assert_not_called()

    @pytest.mark.parametrize("value", ["ACTIONS_HUB", " actions_hub "])
    async def test_the_host_value_is_case_and_space_insensitive(self, value):
        with (
            patch.dict("os.environ", {"ZAMP_SDK_EXECUTION_HOST": value}, clear=True),
            patch.object(ActionExecutor, "_get_action_gateway", return_value=None),
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            ah_mock.return_value = "hub"

            await ActionExecutor.execute("action", {})

            ah_mock.assert_awaited_once()

    async def test_an_unknown_host_raises_rather_than_falling_back(self):
        """A typo must not silently change transport: falling back to the API would send
        an action over HTTP from a process that meant to dispatch it in-process."""
        with patch.dict("os.environ", {"ZAMP_SDK_EXECUTION_HOST": "actionshub"}, clear=True):
            with pytest.raises(ValueError, match="not a known execution host"):
                await ActionExecutor.execute("action", {})


class TestExecuteViaActionsHub:
    """Tests for the private ActionExecutor._execute_via_actions_hub() method."""

    async def test_delegates_to_actions_hub_with_mapped_mode(self):
        fake_ah = MagicMock()
        fake_ah.execute_action = AsyncMock(return_value="ok")

        fake_ah_mode = MagicMock(name="AHExecutionMode")
        fake_ah_mode.TEMPORAL_SYNC = "TEMPORAL_SYNC_SENTINEL"

        constructed: dict = {}

        class FakeAHRetry:
            def __init__(self, **kwargs):
                constructed.update(kwargs)

        with (
            patch.dict(
                "sys.modules",
                {
                    "zamp_public_workflow_sdk": MagicMock(),
                    "zamp_public_workflow_sdk.actions_hub": MagicMock(ActionsHub=fake_ah),
                    "zamp_public_workflow_sdk.actions_hub.constants": MagicMock(
                        ExecutionMode=fake_ah_mode,
                    ),
                    "zamp_public_workflow_sdk.actions_hub.models": MagicMock(),
                    "zamp_public_workflow_sdk.actions_hub.models.core_models": MagicMock(
                        RetryPolicy=FakeAHRetry,
                    ),
                },
            ),
        ):
            result = await ActionExecutor._execute_via_actions_hub(
                action_name="send",
                params={"x": 1},
                summary="s",
                return_type=None,
                execution_mode=ExecutionMode.SYNC,
                action_retry_policy=None,
                action_start_to_close_timeout=timedelta(seconds=30),
            )

            assert result == "ok"
            fake_ah.execute_action.assert_awaited_once()
            kwargs = fake_ah.execute_action.call_args.kwargs
            assert kwargs["execution_mode"] == "TEMPORAL_SYNC_SENTINEL"
            assert "inject_zamp_metadata_context" not in kwargs
            assert "return_type" not in kwargs
            # When the caller passes no policy, the SDK's own default flows through
            # instead of None — guarantees we don't inherit ActionsHub's longer default.
            assert isinstance(kwargs["action_retry_policy"], FakeAHRetry)
            sdk_default = RetryPolicy.default()
            assert constructed["maximum_attempts"] == sdk_default.maximum_attempts
            assert kwargs["action_start_to_close_timeout"] == timedelta(seconds=30)
            # Action name and params are passed positionally.
            args = fake_ah.execute_action.call_args.args
            assert args == ("send", {"x": 1})

    async def test_converts_retry_policy_to_ah_retry_policy(self):
        fake_ah = MagicMock()
        fake_ah.execute_action = AsyncMock(return_value=None)

        fake_ah_mode = MagicMock()
        fake_ah_mode.INLINE = "INLINE_SENTINEL"

        constructed: dict = {}

        class FakeAHRetry:
            def __init__(self, **kwargs):
                constructed.update(kwargs)

        with patch.dict(
            "sys.modules",
            {
                "zamp_public_workflow_sdk": MagicMock(),
                "zamp_public_workflow_sdk.actions_hub": MagicMock(ActionsHub=fake_ah),
                "zamp_public_workflow_sdk.actions_hub.constants": MagicMock(
                    ExecutionMode=fake_ah_mode,
                ),
                "zamp_public_workflow_sdk.actions_hub.models": MagicMock(),
                "zamp_public_workflow_sdk.actions_hub.models.core_models": MagicMock(
                    RetryPolicy=FakeAHRetry,
                ),
            },
        ):
            retry = RetryPolicy.default()
            await ActionExecutor._execute_via_actions_hub(
                action_name="a",
                params={},
                summary=None,
                return_type=None,
                execution_mode=ExecutionMode.INLINE,
                action_retry_policy=retry,
                action_start_to_close_timeout=None,
            )

        assert constructed["maximum_attempts"] == retry.maximum_attempts
        assert constructed["initial_interval"] == retry.initial_interval
        assert constructed["maximum_interval"] == retry.maximum_interval
        assert constructed["backoff_coefficient"] == retry.backoff_coefficient
        forwarded = fake_ah.execute_action.call_args.kwargs["action_retry_policy"]
        assert isinstance(forwarded, FakeAHRetry)


class TestExecuteAction:
    """Tests for the private ActionExecutor._execute_action() method."""

    def _executor(self) -> ActionExecutor:
        return ActionExecutor()

    def _make_config(
        self,
        base_url: str = "https://api.zamp.test",
        auth_token: str = "tok",
    ) -> SdkConfig:
        return SdkConfig(base_url=base_url, auth_token=auth_token)

    async def test_builds_correct_post_body(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-123"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": {"ok": True}}

        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            await self._executor()._execute_action(
                action_name="send_email",
                params={"to": "a@b.com"},
                config=self._make_config(),
            )

            body = mock_client.post.call_args.kwargs["data"]
            assert body["action_name"] == "send_email"
            assert body["params"] == {"to": "a@b.com"}
            assert body["is_external_action"] is True

    async def test_includes_channel_context_in_body_when_provided(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-123"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}
        cc = {
            "channel_type": "conversation",
            "channel_id": str(uuid.uuid4()),
            "streaming_id": "s",
            "message_id": "m",
            "tool_call_id": "t",
            "run_id": "r",
        }
        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            await self._executor()._execute_action(
                action_name="a",
                params={"p": 1},
                config=self._make_config(),
                channel_context=cc,
            )
        assert mock_client.post.call_args.kwargs["data"]["channel_context"] == cc

    async def test_omits_channel_context_from_body_when_none(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-123"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}
        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            await self._executor()._execute_action(
                action_name="a",
                params={"p": 1},
                config=self._make_config(),
            )
        assert "channel_context" not in mock_client.post.call_args.kwargs["data"]

    async def test_sends_sdk_default_retry_policy_when_none_passed(self):
        # When the caller does not supply a retry policy, the SDK must inject its
        # own (short) default so the server doesn't apply its longer fallback.
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-default"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}

        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            await self._executor()._execute_action(
                action_name="fallback",
                params={},
                config=self._make_config(),
            )

            body = mock_client.post.call_args.kwargs["data"]
            sdk_default = RetryPolicy.default()
            assert body["retry_policy"]["maximum_attempts"] == sdk_default.maximum_attempts

    async def test_includes_optional_fields(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-456"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}

        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_attempts=7,
            maximum_interval=timedelta(minutes=2),
            backoff_coefficient=2.0,
        )

        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            await self._executor()._execute_action(
                action_name="process",
                params={},
                config=self._make_config(),
                summary="Test summary",
                action_retry_policy=retry,
                action_start_to_close_timeout=timedelta(minutes=10),
            )

            body = mock_client.post.call_args.kwargs["data"]
            assert body["summary"] == "Test summary"
            # Caller-supplied policy is forwarded verbatim, not overridden by the SDK default.
            assert body["retry_policy"]["maximum_attempts"] == 7
            assert body["start_to_close_timeout_seconds"] == 600.0

    async def test_polls_after_post(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-789"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": {"val": 1}}

        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            result = await self._executor()._execute_action(
                action_name="calc",
                params={},
                config=self._make_config(),
            )

            mock_client.get.assert_awaited()
            assert result == {"val": 1}

    async def test_poll_timeout_extends_with_start_to_close(self):
        # A start-to-close timeout above the default extends the client poll
        # timeout so a long-running action is not abandoned at the default.
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-long"}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=mock_client),
            patch.object(ActionExecutor, "_poll_action_result", new_callable=AsyncMock) as mock_poll,
        ):
            mock_poll.return_value = {"ok": True}
            await self._executor()._execute_action(
                action_name="extract",
                params={},
                config=self._make_config(),
                action_start_to_close_timeout=timedelta(hours=2),
            )

            assert mock_poll.await_args.kwargs["poll_timeout"] == 7200.0

    async def test_poll_timeout_defaults_to_one_hour_when_no_start_to_close(self):
        # With no explicit budget the client polls for the 3600s default ceiling.
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-def"}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=mock_client),
            patch.object(ActionExecutor, "_poll_action_result", new_callable=AsyncMock) as mock_poll,
        ):
            mock_poll.return_value = None
            await self._executor()._execute_action(
                action_name="x",
                params={},
                config=self._make_config(),
            )

            assert mock_poll.await_args.kwargs["poll_timeout"] == 3600.0

    async def test_poll_timeout_not_reduced_below_default(self):
        # A short start-to-close timeout must NOT shrink the poll below the default.
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-short"}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=mock_client),
            patch(f"{_MODULE}.POLL_TIMEOUT_SECONDS", 600.0),
            patch.object(ActionExecutor, "_poll_action_result", new_callable=AsyncMock) as mock_poll,
        ):
            mock_poll.return_value = None
            await self._executor()._execute_action(
                action_name="y",
                params={},
                config=self._make_config(),
                action_start_to_close_timeout=timedelta(seconds=30),
            )

            assert mock_poll.await_args.kwargs["poll_timeout"] == 600.0

    async def test_uses_return_type_model_validate(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-abc"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": {"x": 1}}

        mock_model = MagicMock()
        mock_model.model_validate.return_value = "validated"

        with patch(f"{_MODULE}.HttpClient", return_value=mock_client):
            result = await self._executor()._execute_action(
                action_name="typed",
                params={},
                config=self._make_config(),
                return_type=mock_model,
            )

            mock_model.model_validate.assert_called_once_with({"x": 1})
            assert result == "validated"

    async def test_constructs_client_with_auth_header(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-xyz"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}

        with patch(f"{_MODULE}.HttpClient", return_value=mock_client) as mock_cls:
            await self._executor()._execute_action(
                action_name="test",
                params={},
                config=self._make_config(
                    base_url="https://api.zamp.test",
                    auth_token="my-token",
                ),
            )

            mock_cls.assert_called_once_with(
                base_url="https://api.zamp.test",
                default_headers={"Authorization": "Bearer my-token"},
            )


class TestPostAction:
    """Tests for the private ActionExecutor._post_action() method."""

    def _executor(self) -> ActionExecutor:
        return ActionExecutor()

    async def test_returns_response_on_first_success(self):
        client = AsyncMock()
        client.post.return_value = {"id": "action-1"}

        result = await self._executor()._post_action(client, "/actions", {"a": 1})

        assert result == {"id": "action-1"}
        assert client.post.await_count == 1

    async def test_retries_on_5xx_then_succeeds(self):
        client = AsyncMock()
        client.post.side_effect = [_http_error(500), _http_error(503), {"id": "action-ok"}]

        with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await self._executor()._post_action(client, "/actions", {})

        assert result == {"id": "action-ok"}
        assert client.post.await_count == 3
        # Backoff grows between retries: first wait is the initial interval, then it doubles.
        waits = [c.args[0] for c in mock_sleep.await_args_list]
        assert waits == [1.0, 2.0]

    async def test_does_not_retry_on_4xx(self):
        client = AsyncMock()
        client.post.side_effect = _http_error(404)

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(HttpClientError, match="HTTP 404"),
        ):
            await self._executor()._post_action(client, "/actions", {})

        assert client.post.await_count == 1

    async def test_raises_when_retry_timeout_budget_exhausted(self):
        # Bounded by a time budget (like the poll loop), not an attempt count.
        # sleep is patched, so elapsed advances by the backoff intervals: after
        # 1.0 + 2.0 = 3.0s the next 5xx exceeds retry_timeout=1.5 and re-raises.
        client = AsyncMock()
        client.post.side_effect = _http_error(500)

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(HttpClientError, match="HTTP 500"),
        ):
            await self._executor()._post_action(client, "/actions", {}, retry_timeout=1.5)

        assert client.post.await_count == 3

    async def test_backoff_is_capped_at_max_interval(self):
        client = AsyncMock()
        client.post.side_effect = _http_error(502)

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(HttpClientError),
        ):
            await self._executor()._post_action(client, "/actions", {}, retry_timeout=90.0)

        waits = [c.args[0] for c in mock_sleep.await_args_list]
        assert waits == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]

    async def test_execute_action_retries_post_on_5xx(self):
        # End-to-end through _execute_action: a transient 5xx on create is retried.
        mock_client = AsyncMock()
        mock_client.post.side_effect = [_http_error(500), {"id": "action-retry"}]
        mock_client.get.return_value = {"status": "COMPLETED", "result": {"ok": True}}

        with (
            patch(f"{_MODULE}.HttpClient", return_value=mock_client),
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await self._executor()._execute_action(
                action_name="retryable",
                params={},
                config=SdkConfig(base_url="https://api.zamp.test", auth_token="tok"),
            )

        assert result == {"ok": True}
        assert mock_client.post.await_count == 2


class TestPollActionResult:
    """Tests for the private ActionExecutor._poll_action_result() method."""

    def _executor(self) -> ActionExecutor:
        return ActionExecutor()

    async def test_returns_result_on_completed(self):
        client = AsyncMock()
        client.get.return_value = {"status": "COMPLETED", "result": {"data": 42}}

        with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock):
            result = await self._executor()._poll_action_result(client, "action-1")

        assert result == {"data": 42}

    async def test_raises_on_failed(self):
        client = AsyncMock()
        client.get.return_value = {"status": "FAILED", "error": "boom"}

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="FAILED.*boom"),
        ):
            await self._executor()._poll_action_result(client, "action-2")

    async def test_raises_on_canceled(self):
        client = AsyncMock()
        client.get.return_value = {"status": "CANCELED", "error": "cancelled"}

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="CANCELED"),
        ):
            await self._executor()._poll_action_result(client, "action-3")

    async def test_raises_on_timed_out(self):
        client = AsyncMock()
        client.get.return_value = {"status": "TIMED_OUT", "error": "timeout"}

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="TIMED_OUT"),
        ):
            await self._executor()._poll_action_result(client, "action-4")

    async def test_raises_timeout_error_when_poll_exceeds_limit(self):
        client = AsyncMock()
        client.get.return_value = {"status": "RUNNING"}

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}.POLL_TIMEOUT_SECONDS", 2.0),
            patch(f"{_MODULE}.POLL_INITIAL_INTERVAL_SECONDS", 1.0),
            pytest.raises(TimeoutError, match="did not complete"),
        ):
            await self._executor()._poll_action_result(client, "action-5")

    async def test_respects_poll_timeout_param(self):
        # The explicit poll_timeout arg bounds the loop, independent of the
        # module-level POLL_TIMEOUT_SECONDS default.
        client = AsyncMock()
        client.get.return_value = {"status": "RUNNING"}

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}.POLL_INITIAL_INTERVAL_SECONDS", 1.0),
            pytest.raises(TimeoutError, match="did not complete within 2.0s"),
        ):
            await self._executor()._poll_action_result(client, "action-pt", poll_timeout=2.0)

    async def test_polls_until_completed(self):
        client = AsyncMock()
        client.get.side_effect = [
            {"status": "RUNNING"},
            {"status": "RUNNING"},
            {"status": "COMPLETED", "result": {"done": True}},
        ]

        with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock):
            result = await self._executor()._poll_action_result(client, "action-6")

        assert result == {"done": True}
        assert client.get.await_count == 3

    async def test_raises_on_unexpected_status(self):
        client = AsyncMock()
        client.get.return_value = {"status": "UNKNOWN_STATE"}

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="unexpected status"),
        ):
            await self._executor()._poll_action_result(client, "action-7")

    async def test_keeps_polling_through_5xx(self):
        # A transient 5xx while polling must not fail the action; polling
        # resumes and picks up the terminal status once the server recovers.
        client = AsyncMock()
        client.get.side_effect = [
            {"status": "RUNNING"},
            _http_error(500),
            _http_error(503),
            {"status": "COMPLETED", "result": {"done": True}},
        ]

        with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock):
            result = await self._executor()._poll_action_result(client, "action-5xx")

        assert result == {"done": True}
        assert client.get.await_count == 4

    async def test_persistent_5xx_times_out_within_poll_budget(self):
        # If the server never recovers, polling is still bounded by poll_timeout
        # and surfaces a TimeoutError rather than looping forever.
        client = AsyncMock()
        client.get.side_effect = _http_error(502)

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}.POLL_INITIAL_INTERVAL_SECONDS", 1.0),
            pytest.raises(TimeoutError, match="did not complete within 2.0s"),
        ):
            await self._executor()._poll_action_result(client, "action-5xx-forever", poll_timeout=2.0)

    async def test_non_5xx_during_poll_propagates(self):
        # A 4xx (non-transient) while polling should surface, not be swallowed.
        client = AsyncMock()
        client.get.side_effect = _http_error(404)

        with (
            patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(HttpClientError, match="HTTP 404"),
        ):
            await self._executor()._poll_action_result(client, "action-4xx")


class TestChannelContextOnApiCall:
    """The SDK resolves the caller's channel context once and attaches it to the POST
    /actions body, so individual actions don't each have to send it."""

    async def test_sandbox_execute_attaches_channel_context_to_body(self):
        cid = str(uuid.uuid4())
        env = {
            "ZAMP_BASE_URL": "https://api.zamp.test",
            "ZAMP_AUTH_TOKEN": "tok",
            "ZAMP_CHANNEL_TYPE": "conversation",
            "ZAMP_CHANNEL_ID": cid,
            "ZAMP_STREAMING_ID": "s",
            "ZAMP_MESSAGE_ID": "m",
            "ZAMP_TOOL_CALL_ID": "t",
            "ZAMP_RUN_ID": "r",
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-1"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}
        with (
            patch.dict("os.environ", env, clear=True),
            patch(f"{_MODULE}.HttpClient", return_value=mock_client),
        ):
            await ActionExecutor.execute("some_action", {"p": 1})
        cc = mock_client.post.call_args.kwargs["data"]["channel_context"]
        assert cc["channel_id"] == cid
        assert cc["channel_type"] == "conversation"

    async def test_sandbox_execute_omits_channel_context_when_env_incomplete(self):
        # Only channel type/id in the env (no streaming/message/tool/run) -> no valid
        # ChannelContext -> nothing attached; the action still goes through.
        env = {
            "ZAMP_BASE_URL": "https://api.zamp.test",
            "ZAMP_AUTH_TOKEN": "tok",
            "ZAMP_CHANNEL_TYPE": "conversation",
            "ZAMP_CHANNEL_ID": str(uuid.uuid4()),
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-1"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}
        with (
            patch.dict("os.environ", env, clear=True),
            patch(f"{_MODULE}.HttpClient", return_value=mock_client),
        ):
            await ActionExecutor.execute("some_action", {"p": 1})
        assert "channel_context" not in mock_client.post.call_args.kwargs["data"]


class _Weird:
    def __str__(self) -> str:
        return "<weird>"


def test_capture_action_step_serializable_result_stored_asis():
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"a": 1}, {"ok": True})
    steps = drain_log_capture()
    assert steps[0]["output"] == {"ok": True}
    json.dumps(steps[0])


def test_capture_action_step_non_serializable_result_degrades_to_string():
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"a": 1}, _Weird())
    steps = drain_log_capture()
    assert steps[0]["output"] == "<weird>"
    json.dumps(steps[0])  # the whole step is JSON-safe


def test_capture_action_step_cyclic_result_does_not_hang_and_is_json_safe():
    """The cycle must not survive into the buffer, and opening the dict one level must not
    recurse into it."""
    start_log_capture()
    cyc: dict = {}
    cyc["self"] = cyc
    ActionExecutor._capture_action_step("act", {"a": 1}, cyc)
    steps = drain_log_capture()
    assert isinstance(steps[0]["output"]["self"], str)  # stringified, not the live cycle
    json.dumps(steps[0])


def test_capture_action_step_keeps_the_serializable_result_fields_alongside_the_bad_one():
    """The motivating case: one unserializable field must not flatten the whole result. A
    datetime is JSON-unsafe even though Pydantic would carry it, so this is the common one."""
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"a": 1}, {"rows": [{"n": 1}], "at": _Weird()})
    steps = drain_log_capture()
    assert steps[0]["output"] == {"rows": [{"n": 1}], "at": "<weird>"}
    json.dumps(steps[0])


def test_capture_action_step_degrades_only_the_bad_items_of_a_list_result():
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"a": 1}, [{"n": 1}, _Weird()])
    steps = drain_log_capture()
    assert steps[0]["output"] == [{"n": 1}, "<weird>"]
    json.dumps(steps[0])


def test_capture_action_step_non_serializable_params_do_not_sink_the_step():
    """An INLINE dispatch never serializes params, so reaching the capture is no proof they
    can cross the Temporal boundary. A bad input must not poison the whole step."""
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"who": _Weird()}, {"ok": True})
    steps = drain_log_capture()
    assert steps[0]["input"] == {"who": "<weird>"}
    assert steps[0]["output"] == {"ok": True}
    json.dumps(steps[0])


def test_capture_action_step_keeps_the_serializable_params_alongside_the_bad_one():
    """Per-entry, not whole-dict: losing every param because one is unserializable would
    throw away the more useful half of the step."""
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"keep": {"n": 1}, "drop": _Weird()}, None)
    steps = drain_log_capture()
    assert steps[0]["input"] == {"keep": {"n": 1}, "drop": "<weird>"}
    json.dumps(steps[0])


def test_capture_action_step_cyclic_params_do_not_hang():
    start_log_capture()
    cyc: dict = {}
    cyc["self"] = cyc
    ActionExecutor._capture_action_step("act", {"cyc": cyc}, None)
    steps = drain_log_capture()
    assert isinstance(steps[0]["input"]["cyc"], str)
    json.dumps(steps[0])


def test_capture_action_step_non_string_param_key_is_made_json_safe():
    start_log_capture()
    ActionExecutor._capture_action_step("act", {(1, 2): "v"}, None)
    steps = drain_log_capture()
    json.dumps(steps[0])


def test_capture_action_step_non_dict_params_are_stringified():
    start_log_capture()
    ActionExecutor._capture_action_step("act", _Weird(), None)  # type: ignore[arg-type]
    steps = drain_log_capture()
    assert steps[0]["input"] == "<weird>"
    json.dumps(steps[0])


class _HostileDict(dict):
    """A mapping that raises while being inspected, not while being serialized."""

    def items(self):  # type: ignore[override]
        raise RuntimeError("boom")


def test_capture_action_step_never_raises_into_the_caller():
    """The action has already succeeded and its result is about to be returned, so a value
    that misbehaves under inspection must cost the log line and nothing else."""
    start_log_capture()
    ActionExecutor._capture_action_step("act", _HostileDict(a=1), {"ok": True})
    assert drain_log_capture() == []


def test_capture_action_step_never_raises_on_a_hostile_result():
    start_log_capture()
    ActionExecutor._capture_action_step("act", {"a": 1}, _HostileDict(b=2))
    assert drain_log_capture() == []


class _NoStr:
    """``str()`` on this raises, so even the fallback has to have a fallback."""

    def __str__(self) -> str:
        raise RuntimeError("nope")


def _safe(value):
    return ActionExecutor._json_safe(value, half="output", action_name="act")


class TestAsString:
    def test_uses_str_when_it_works(self):
        assert ActionExecutor._as_string(_Weird()) == "<weird>"

    def test_names_the_type_when_str_itself_raises(self):
        assert ActionExecutor._as_string(_NoStr()) == "<unserializable _NoStr>"


class TestValueOrString:
    def test_a_serializable_value_comes_back_untouched(self):
        value = {"a": [1, {"b": None}]}
        assert ActionExecutor._value_or_string(value) is value

    def test_a_bad_value_becomes_a_string(self):
        assert ActionExecutor._value_or_string(_Weird()) == "<weird>"

    @pytest.mark.parametrize("value", [None, False, 0, "", [], {}, 0.0])
    def test_falsy_but_serializable_values_are_not_mistaken_for_bad_ones(self, value):
        """The check is "does it serialize", not "is it truthy" - a plain ``if not value``
        would quietly stringify every legitimate empty result."""
        assert ActionExecutor._value_or_string(value) is value


class TestJsonSafeHappyPath:
    def test_the_same_object_is_returned_not_a_copy(self):
        """The happy path must not rebuild the value: it is the common case, and a copy
        would cost time on every action call and hide later mutation."""
        value = {"a": 1, "b": [2, 3]}
        assert _safe(value) is value

    def test_nothing_is_logged_when_the_value_serializes(self):
        with patch(f"{_MODULE}.logger") as logger:
            _safe({"a": 1})
        logger.warning.assert_not_called()

    def test_degrading_logs_once_naming_the_half_and_the_action(self):
        with patch(f"{_MODULE}.logger") as logger:
            ActionExecutor._json_safe({"a": _Weird()}, half="input", action_name="charge_card")
        assert logger.warning.call_count == 1
        kwargs = logger.warning.call_args.kwargs
        assert kwargs["half"] == "input"
        assert kwargs["action_name"] == "charge_card"
        assert kwargs["value_type"] == "dict"
        assert "error" in kwargs


class TestJsonSafeContainers:
    def test_a_dict_keeps_its_good_entries(self):
        assert _safe({"keep": {"n": 1}, "drop": _Weird()}) == {"keep": {"n": 1}, "drop": "<weird>"}

    def test_a_list_keeps_its_good_items(self):
        assert _safe([{"n": 1}, _Weird(), "x"]) == [{"n": 1}, "<weird>", "x"]

    def test_a_tuple_with_a_bad_item_comes_back_as_a_list(self):
        """JSON has no tuple, so the shape a caller gets back is a list."""
        assert _safe((1, _Weird())) == [1, "<weird>"]

    def test_a_fully_serializable_tuple_is_left_alone(self):
        value = (1, 2)
        assert _safe(value) is value

    def test_a_set_is_stringified_whole(self):
        """A set is neither a mapping nor a sequence here, so there is nothing to open."""
        assert _safe({"tags": {1}}) == {"tags": "{1}"}

    def test_containers_are_opened_one_level_only(self):
        """The deliberate limit: a full walk would cost every call, and a self-referential
        value would not terminate. The bad value is two levels down, so the whole inner
        container is stringified rather than rebuilt."""
        out = _safe({"outer": {"inner": _Weird()}})
        assert list(out) == ["outer"]
        assert isinstance(out["outer"], str)  # the whole inner dict, flattened
        assert "inner" in out["outer"]

    def test_a_self_referential_value_terminates(self):
        cyc: dict = {}
        cyc["self"] = cyc
        assert isinstance(_safe(cyc)["self"], str)

    def test_a_bad_value_that_is_not_a_container_is_stringified(self):
        assert _safe(_Weird()) == "<weird>"

    @pytest.mark.parametrize("value", [{}, [], ()])
    def test_empty_containers_pass_straight_through(self, value):
        assert _safe(value) is value


class TestJsonSafeKeys:
    def test_non_string_keys_survive_untouched_while_the_dict_still_serializes(self):
        """``json.dumps`` coerces int keys itself, so nothing needs doing on the happy path."""
        value = {1: "a", True: "b"}
        assert _safe(value) is value

    def test_a_non_string_key_is_stringified_when_the_dict_degrades(self):
        assert _safe({(1, 2): _Weird()}) == {"(1, 2)": "<weird>"}

    def test_a_stringified_key_can_collide_with_an_existing_string_key(self):
        """Documented loss, not an accident: on the degraded path an int key becomes "1",
        which overwrites a sibling "1". Needs a dict mixing both key types *and* an
        unserializable value, so it is vanishingly rare - and the alternative (dropping the
        whole input) is worse."""
        assert _safe({1: "first", "1": _Weird()}) == {"1": "<weird>"}


class TestJsonSafeInvariant:
    @pytest.mark.parametrize(
        "value",
        [
            _Weird(),
            _NoStr(),
            b"\xff\xfe",
            {1},
            (x for x in [1]),
            {"a": _NoStr(), "b": b"x", "c": {1}},
            [_NoStr(), b"y"],
            {"nested": {"deep": _Weird()}},
        ],
    )
    def test_whatever_goes_in_the_result_can_be_serialized(self, value):
        """The one property that matters: after this, the host can always serialize it."""
        json.dumps(_safe(value))

    def test_nan_and_inf_pass_the_probe_although_they_are_not_valid_json(self):
        """Known gap, pinned so it is a decision rather than a surprise: ``json.dumps``
        accepts them and emits bare ``NaN``/``Infinity``, which strict parsers reject. The
        probe therefore lets them through unchanged."""
        assert json.dumps(float("nan")) == "NaN"
        value = {"n": float("nan"), "i": float("inf")}
        assert _safe(value) is value


class TestCaptureIsFailSafe:
    """Capture runs after the action has already succeeded and its result is about to be
    returned, so no failure inside it may change what the caller sees. Each dependency and
    helper is broken in turn - a guard that only covers the paths we thought of is not a
    guard."""

    @pytest.mark.parametrize("dependency", ["capture_active", "capture_step"])
    def test_a_broken_capture_dependency_is_swallowed(self, dependency):
        start_log_capture()
        with patch(f"{_MODULE}.{dependency}", side_effect=RuntimeError("boom")):
            ActionExecutor._capture_action_step("act", {"a": 1}, {"ok": True})

    @pytest.mark.parametrize("helper", ["_json_safe", "_value_or_string", "_stringify_bad_values", "_as_string"])
    def test_a_broken_helper_is_swallowed(self, helper):
        start_log_capture()
        with patch.object(ActionExecutor, helper, side_effect=RuntimeError("boom")):
            ActionExecutor._capture_action_step("act", {"a": _Weird()}, _Weird())

    def test_the_swallowed_failure_is_logged_once_naming_the_action(self):
        start_log_capture()
        with (
            patch(f"{_MODULE}.capture_step", side_effect=RuntimeError("boom")),
            patch(f"{_MODULE}.logger") as logger,
        ):
            ActionExecutor._capture_action_step("charge_card", {"a": 1}, {"ok": True})
        assert logger.warning.call_count == 1
        assert logger.warning.call_args.kwargs["action_name"] == "charge_card"

    def test_a_failed_capture_leaves_the_buffer_usable(self):
        """A broken step must not poison the buffer for the steps that follow."""
        start_log_capture()
        with patch(f"{_MODULE}.capture_step", side_effect=RuntimeError("boom")):
            ActionExecutor._capture_action_step("bad", {"a": 1}, {"ok": True})
        ActionExecutor._capture_action_step("good", {"b": 2}, {"ok": True})
        steps = drain_log_capture()
        assert [s["name"] for s in steps] == ["good"]

    async def test_execute_still_returns_its_result_when_capture_explodes(self, monkeypatch):
        """The property that actually matters: a caller gets the action's result even if
        every part of the capture is broken."""
        sentinel = {"invoice": "INV-1"}

        async def dispatch(**kwargs):
            return sentinel

        monkeypatch.setattr(ActionExecutor, "_execute_via_api", staticmethod(dispatch))
        start_log_capture()
        with patch(f"{_MODULE}.capture_step", side_effect=RuntimeError("boom")):
            result = await ActionExecutor.execute("get_invoice", {"id": "1"})
        assert result is sentinel

    async def test_execute_still_propagates_a_real_action_failure(self, monkeypatch):
        """The guard must not swallow the action's own error - only the capture's."""

        async def dispatch(**kwargs):
            raise HttpClientError("upstream down")

        monkeypatch.setattr(ActionExecutor, "_execute_via_api", staticmethod(dispatch))
        start_log_capture()
        with pytest.raises(HttpClientError, match="upstream down"):
            await ActionExecutor.execute("get_invoice", {"id": "1"})
