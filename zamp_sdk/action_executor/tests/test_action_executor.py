from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig

_MODULE = "zamp_sdk.action_executor.action_executor"


class TestExecute:
    """Tests for the public ActionExecutor.execute() entry point."""

    async def test_explicit_config_forwarded(self, base_url, auth_token):
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock:
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
        env = {"ZAMP_BASE_URL": base_url, "ZAMP_AUTH_TOKEN": auth_token}
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
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(KeyError, match="ZAMP_BASE_URL"),
        ):
            await ActionExecutor.execute("action", {})

    async def test_forwards_all_params(self, base_url, auth_token):
        retry = RetryPolicy.default()
        timeout = timedelta(minutes=5)

        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock:
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
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as mock:
            mock.return_value = {"amount": 42}

            result = await ActionExecutor.execute(
                "calc",
                {},
                base_url=base_url,
                auth_token=auth_token,
            )

            assert result == {"amount": 42}


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
