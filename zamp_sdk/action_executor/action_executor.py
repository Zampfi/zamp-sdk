import asyncio
import os
from datetime import timedelta
from typing import Any

import structlog

from zamp_sdk.action_executor.constants import (
    IN_PROGRESS_STATUSES,
    POLL_INITIAL_INTERVAL_SECONDS,
    POLL_MAX_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    RETRY_5XX_BACKOFF_COEFFICIENT,
    RETRY_5XX_INITIAL_INTERVAL_SECONDS,
    RETRY_5XX_MAX_ATTEMPTS,
    RETRY_5XX_MAX_INTERVAL_SECONDS,
    SUCCESS_STATUSES,
    TERMINAL_FAILURE_STATUSES,
)
from zamp_sdk.action_executor.execution_mode import ExecutionMode, resolve_ah_execution_mode
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig
from zamp_sdk.action_executor.utils import HttpClient, HttpClientError

logger = structlog.get_logger(__name__)


def _is_retryable_5xx(exc: HttpClientError) -> bool:
    """A 5xx response is a transient server error worth retrying."""
    return exc.status_code is not None and 500 <= exc.status_code < 600


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

    @staticmethod
    def _is_inside_sandbox() -> bool:
        return os.environ.get("INSIDE_SANDBOX") == "true"

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
        execution_mode: ExecutionMode | None = None,
        action_retry_policy: RetryPolicy | None = None,
        action_start_to_close_timeout: timedelta | None = None,
    ) -> Any:
        if cls._is_inside_sandbox():
            return await cls._execute_via_api(
                action_name=action_name,
                params=params,
                base_url=base_url,
                auth_token=auth_token,
                summary=summary,
                return_type=return_type,
                action_retry_policy=action_retry_policy,
                action_start_to_close_timeout=action_start_to_close_timeout,
            )
        return await cls._execute_via_actions_hub(
            action_name=action_name,
            params=params,
            summary=summary,
            return_type=return_type,
            execution_mode=execution_mode,
            action_retry_policy=action_retry_policy,
            action_start_to_close_timeout=action_start_to_close_timeout,
        )

    @classmethod
    async def _execute_via_api(
        cls,
        action_name: str,
        params: dict[str, Any],
        *,
        base_url: str | None,
        auth_token: str | None,
        summary: str | None,
        return_type: type | None,
        action_retry_policy: RetryPolicy | None,
        action_start_to_close_timeout: timedelta | None,
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
    async def _execute_via_actions_hub(
        cls,
        action_name: str,
        params: dict[str, Any],
        *,
        summary: str | None,
        return_type: type | None,
        execution_mode: ExecutionMode | None,
        action_retry_policy: RetryPolicy | None,
        action_start_to_close_timeout: timedelta | None,
    ) -> Any:
        from zamp_public_workflow_sdk.actions_hub import ActionsHub
        from zamp_public_workflow_sdk.actions_hub.models.core_models import (
            RetryPolicy as AHRetryPolicy,
        )

        ah_mode = resolve_ah_execution_mode(execution_mode)
        effective_retry_policy = action_retry_policy if action_retry_policy is not None else RetryPolicy.default()
        ah_retry_policy = AHRetryPolicy(**effective_retry_policy.model_dump())

        return await ActionsHub.execute_action(
            action_name,
            params,
            summary=summary,
            execution_mode=ah_mode,
            action_retry_policy=ah_retry_policy,
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

        # Always send the SDK's retry policy so the server doesn't fall back to
        # its own (longer) default; callers can still override per-call.
        effective_retry_policy = action_retry_policy if action_retry_policy is not None else RetryPolicy.default()

        body: dict = {
            "action_name": action_name,
            "params": params,
            "is_external_action": True,
            "retry_policy": effective_retry_policy.model_dump(mode="json"),
        }
        if summary is not None:
            body["summary"] = summary
        if action_start_to_close_timeout is not None:
            body["start_to_close_timeout_seconds"] = action_start_to_close_timeout.total_seconds()

        response = await cls._post_action_with_5xx_retries(client, "/actions", body)
        action_id = response["id"]
        poll_timeout = POLL_TIMEOUT_SECONDS
        if action_start_to_close_timeout is not None:
            poll_timeout = max(POLL_TIMEOUT_SECONDS, action_start_to_close_timeout.total_seconds())
        result = await cls._poll_action_result(client, action_id, poll_timeout=poll_timeout)

        if return_type and hasattr(return_type, "model_validate"):
            return return_type.model_validate(result)
        return result

    @classmethod
    async def _post_action_with_5xx_retries(
        cls,
        client: HttpClient,
        endpoint: str,
        body: dict,
    ) -> dict:
        """POST ``body`` to ``endpoint``, retrying on 5xx with exponential backoff.

        Retries up to ``RETRY_5XX_MAX_ATTEMPTS`` times on a transient server
        error so a momentary 5xx doesn't fail the action before it is even
        created. Non-5xx errors (e.g. 4xx, network) propagate immediately.
        """
        interval = RETRY_5XX_INITIAL_INTERVAL_SECONDS

        for attempt in range(1, RETRY_5XX_MAX_ATTEMPTS + 1):
            try:
                return await client.post(endpoint, data=body)
            except HttpClientError as exc:
                # Exhausted or non-transient: surface the original error.
                if not _is_retryable_5xx(exc) or attempt == RETRY_5XX_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "action POST returned 5xx, retrying",
                    endpoint=endpoint,
                    status_code=exc.status_code,
                    attempt=attempt,
                    max_attempts=RETRY_5XX_MAX_ATTEMPTS,
                    retry_in_seconds=interval,
                )
                await asyncio.sleep(interval)
                interval = min(interval * RETRY_5XX_BACKOFF_COEFFICIENT, RETRY_5XX_MAX_INTERVAL_SECONDS)

        # Unreachable: the final attempt either returns or re-raises above.
        raise RuntimeError(f"action POST to {endpoint} exhausted retries without a result")

    @staticmethod
    async def _poll_action_result(
        client: HttpClient,
        action_id: str,
        poll_timeout: float = POLL_TIMEOUT_SECONDS,
    ) -> Any:
        """Poll ``GET /actions/{id}`` with exponential backoff until a terminal state.

        Polls for up to ``poll_timeout`` seconds (default ``POLL_TIMEOUT_SECONDS``);
        callers pass a larger value for long-running actions via
        ``action_start_to_close_timeout``.
        """
        interval = POLL_INITIAL_INTERVAL_SECONDS
        elapsed = 0.0

        while elapsed < poll_timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                data = await client.get(f"/actions/{action_id}")
            except HttpClientError as exc:
                # A transient 5xx while polling shouldn't fail the action: keep
                # polling (with backoff) until the action completes or the
                # overall poll_timeout is hit. Non-5xx errors still propagate.
                if not _is_retryable_5xx(exc):
                    raise
                logger.warning(
                    "action poll returned 5xx, continuing to poll",
                    action_id=action_id,
                    status_code=exc.status_code,
                    elapsed=elapsed,
                    poll_timeout=poll_timeout,
                )
                interval = min(interval * 2, POLL_MAX_INTERVAL_SECONDS)
                continue

            action_status = data["status"]

            if action_status in SUCCESS_STATUSES:
                return data.get("result")
            if action_status in TERMINAL_FAILURE_STATUSES:
                raise RuntimeError(f"Action {action_id} {action_status}: {data.get('error', 'unknown error')}")
            if action_status not in IN_PROGRESS_STATUSES:
                raise RuntimeError(f"Action {action_id} unexpected status: {action_status}")
            interval = min(interval * 2, POLL_MAX_INTERVAL_SECONDS)

        raise TimeoutError(f"Action {action_id} did not complete within {poll_timeout}s")
