from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.execution_mode import ExecutionMode
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig

_MODULE = "zamp_sdk.action_executor.action_executor"
_SANDBOX_ENV = {"INSIDE_SANDBOX": "true"}


class TestExecute:
    """Tests for the public ActionExecutor.execute() entry point (sandbox path)."""

    async def test_explicit_config_forwarded(self, base_url, auth_token):
        with (
            patch.dict("os.environ", _SANDBOX_ENV, clear=False),
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
        env = {"ZAMP_BASE_URL": base_url, "ZAMP_AUTH_TOKEN": auth_token, **_SANDBOX_ENV}
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
            patch.dict("os.environ", _SANDBOX_ENV, clear=True),
            pytest.raises(KeyError, match="ZAMP_BASE_URL"),
        ):
            await ActionExecutor.execute("action", {})

    async def test_forwards_all_params(self, base_url, auth_token):
        retry = RetryPolicy.default()
        timeout = timedelta(minutes=5)

        with (
            patch.dict("os.environ", _SANDBOX_ENV, clear=False),
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
            patch.dict("os.environ", _SANDBOX_ENV, clear=False),
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
    """Tests for the sandbox-vs-actions-hub dispatch in ActionExecutor.execute()."""

    async def test_sandbox_env_takes_http_path(self, base_url, auth_token):
        with (
            patch.dict("os.environ", _SANDBOX_ENV, clear=False),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api_mock,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            api_mock.return_value = "sandbox-result"

            result = await ActionExecutor.execute(
                "action",
                {},
                base_url=base_url,
                auth_token=auth_token,
                execution_mode=ExecutionMode.SYNC,
            )

            assert result == "sandbox-result"
            api_mock.assert_awaited_once()
            ah_mock.assert_not_called()
            kwargs = api_mock.call_args.kwargs
            assert kwargs["base_url"] == base_url
            assert kwargs["auth_token"] == auth_token

    async def test_non_sandbox_uses_actions_hub_path(self, base_url, auth_token):
        with (
            patch.dict("os.environ", {}, clear=True),
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

    async def test_sandbox_value_other_than_true_uses_actions_hub(self):
        with (
            patch.dict("os.environ", {"INSIDE_SANDBOX": "false"}, clear=True),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api_mock,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as ah_mock,
        ):
            ah_mock.return_value = "hub"

            await ActionExecutor.execute("action", {})

            ah_mock.assert_awaited_once()
            api_mock.assert_not_called()


class TestExecuteViaActionsHub:
    """Tests for the private ActionExecutor._execute_via_actions_hub() method."""

    async def test_delegates_to_actions_hub_with_mapped_mode(self):
        fake_ah = MagicMock()
        fake_ah.execute_action = AsyncMock(return_value="ok")

        fake_ah_mode = MagicMock(name="AHExecutionMode")
        fake_ah_mode.TEMPORAL_SYNC = "TEMPORAL_SYNC_SENTINEL"

        fake_retry_cls = MagicMock(name="AHRetryPolicy")

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
                        RetryPolicy=fake_retry_cls,
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
            assert kwargs["inject_zamp_metadata_context"] is True
            assert kwargs["action_retry_policy"] is None
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

    async def test_includes_optional_fields(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"id": "action-456"}
        mock_client.get.return_value = {"status": "COMPLETED", "result": None}

        retry = RetryPolicy.default()

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
            assert "retry_policy" in body
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
