import asyncio
import os
from datetime import timedelta
from typing import Any

from zamp_sdk.action_executor.constants import (
    IN_PROGRESS_STATUSES,
    POLL_INITIAL_INTERVAL_SECONDS,
    POLL_MAX_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    SUCCESS_STATUSES,
    TERMINAL_FAILURE_STATUSES,
)
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig
from zamp_sdk.action_executor.utils import HttpClient


class ActionExecutor:
    """Entry point for executing actions on the Zamp platform.

    Configuration can be supplied explicitly via ``base_url`` / ``auth_token``
    keyword arguments, or read automatically from the ``ZAMP_BASE_URL`` and
    ``ZAMP_AUTH_TOKEN`` environment variables.
    """

    @classmethod
    def _resolve_config(
        cls,
        base_url: str | None,
        auth_token: str | None,
    ) -> SdkConfig:
        """Build config from explicit values, falling back to environment variables."""
        return SdkConfig(
            base_url=base_url or os.environ["ZAMP_BASE_URL"],
            auth_token=auth_token or os.environ["ZAMP_AUTH_TOKEN"],
        )

    @classmethod
    async def execute(
        cls,
        action_name: str,
        params: dict[str, Any],
        *,
        base_url: str | None = None,
        auth_token: str | None = None,
        summary: str | None = None,
        return_type: type | None = None,
        action_retry_policy: RetryPolicy | None = None,
        action_start_to_close_timeout: timedelta | None = None,
    ) -> Any:
        config = cls._resolve_config(base_url, auth_token)

        return await cls._execute_action(
            action_name=action_name,
            params=params,
            config=config,
            return_type=return_type,
            summary=summary,
            action_retry_policy=action_retry_policy,
            action_start_to_close_timeout=action_start_to_close_timeout,
        )

    @classmethod
    async def _execute_action(
        cls,
        action_name: str,
        params: dict[str, Any],
        *,
        config: SdkConfig,
        return_type: type | None = None,
        summary: str | None = None,
        action_retry_policy: RetryPolicy | None = None,
        action_start_to_close_timeout: timedelta | None = None,
    ) -> Any:
        """Post to ``{config.base_url}/actions`` and poll until a terminal state."""
        client = HttpClient(
            base_url=config.base_url,
            default_headers={"Authorization": f"Bearer {config.auth_token}"},
        )

        body: dict = {
            "action_name": action_name,
            "params": params,
            "is_external_action": True,
        }
        if summary is not None:
            body["summary"] = summary
        if action_retry_policy is not None:
            body["retry_policy"] = action_retry_policy.model_dump(mode="json")
        if action_start_to_close_timeout is not None:
            body["start_to_close_timeout_seconds"] = action_start_to_close_timeout.total_seconds()

        response = await client.post("/actions", data=body)
        action_id = response["id"]
        result = await cls._poll_action_result(client, action_id)

        if return_type and hasattr(return_type, "model_validate"):
            return return_type.model_validate(result)
        return result

    @staticmethod
    async def _poll_action_result(client: HttpClient, action_id: str) -> Any:
        """Poll ``GET /actions/{id}`` with exponential backoff until a terminal state."""
        interval = POLL_INITIAL_INTERVAL_SECONDS
        elapsed = 0.0

        while elapsed < POLL_TIMEOUT_SECONDS:
            await asyncio.sleep(interval)
            elapsed += interval

            data = await client.get(f"/actions/{action_id}")
            action_status = data["status"]

            if action_status in SUCCESS_STATUSES:
                return data.get("result")
            if action_status in TERMINAL_FAILURE_STATUSES:
                raise RuntimeError(f"Action {action_id} {action_status}: {data.get('error', 'unknown error')}")
            if action_status not in IN_PROGRESS_STATUSES:
                raise RuntimeError(f"Action {action_id} unexpected status: {action_status}")
            interval = min(interval * 2, POLL_MAX_INTERVAL_SECONDS)

        raise TimeoutError(f"Action {action_id} did not complete within {POLL_TIMEOUT_SECONDS}s")
