import asyncio
import json
import os
from datetime import timedelta
from typing import Any, Callable

from zamp_sdk.action_executor.constants import (
    IN_PROGRESS_STATUSES,
    INLINE_REQUEST_TIMEOUT_MARGIN_SECONDS,
    INLINE_SERVER_MAX_SECONDS,
    POLL_BACKOFF_COEFFICIENT,
    POLL_INITIAL_INTERVAL_SECONDS,
    POLL_MAX_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    POST_RETRY_BACKOFF_COEFFICIENT,
    POST_RETRY_INITIAL_INTERVAL_SECONDS,
    POST_RETRY_MAX_INTERVAL_SECONDS,
    POST_RETRY_TIMEOUT_SECONDS,
    SUCCESS_STATUSES,
    TERMINAL_FAILURE_STATUSES,
    TERMINAL_STATUSES,
)
from zamp_sdk.action_executor.execution_mode import ExecutionMode, resolve_ah_execution_mode
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig
from zamp_sdk.action_executor.utils import HttpClient, HttpClientError
from zamp_sdk.capture import capture_active, capture_step
from zamp_sdk.context import ExecutionHost, current_execution_host, resolve_channel_context
from zamp_sdk.logger import get_logger

logger = get_logger(__name__)


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
        execution_mode: ExecutionMode | None = None,
        action_retry_policy: RetryPolicy | None = None,
        action_start_to_close_timeout: timedelta | None = None,
    ) -> Any:
        """Run ``action_name`` with ``params`` and return its result.

        ``execution_mode`` picks the transport on the API path. ``INLINE`` asks the
        platform to run the action inside the ``POST /actions`` request and answer
        with its result: one round trip, no polling, and no retries — the platform
        refuses actions that need them. ``SYNC``, ``ASYNC`` and ``None`` keep the
        durable path, where the platform runs the action on Temporal and this client
        polls ``GET /actions/{id}``. On the ActionsHub host the same member maps onto
        the hub's own mode of that name.
        """
        if current_execution_host() is ExecutionHost.ACTIONS_HUB:
            gateway = cls._get_action_gateway()
            if gateway is not None and not await cls._is_registered_locally(action_name):
                result = await gateway(
                    action_name,
                    params,
                    summary=summary,
                    return_type=return_type,
                    action_retry_policy=action_retry_policy,
                    action_start_to_close_timeout=action_start_to_close_timeout,
                )
            else:
                result = await cls._execute_via_actions_hub(
                    action_name=action_name,
                    params=params,
                    summary=summary,
                    return_type=return_type,
                    execution_mode=execution_mode,
                    action_retry_policy=action_retry_policy,
                    action_start_to_close_timeout=action_start_to_close_timeout,
                )
        else:
            result = await cls._execute_via_api(
                action_name=action_name,
                params=params,
                base_url=base_url,
                auth_token=auth_token,
                summary=summary,
                return_type=return_type,
                execution_mode=execution_mode,
                action_retry_policy=action_retry_policy,
                action_start_to_close_timeout=action_start_to_close_timeout,
            )
        cls._capture_action_step(action_name, params, result)
        return result

    @staticmethod
    def _as_string(value: Any) -> str:
        """Last-resort stand-in for a value that cannot be serialized."""
        try:
            return str(value)
        except Exception:
            return f"<unserializable {type(value).__name__}>"

    @classmethod
    def _value_or_string(cls, value: Any) -> Any:
        """The value itself when it serializes, else a stringified stand-in."""
        try:
            json.dumps(value)
            return value
        except Exception:
            return cls._as_string(value)

    @classmethod
    def _stringify_bad_values(cls, value: Any) -> Any:
        """The same shape with only the parts that cannot serialize replaced by strings.

        One bad field should cost that field, not the whole half of the step: an action
        returning ``{"rows": [...], "at": datetime}`` keeps its rows. Containers are opened
        one level only - a full walk would add latency to every action call, and a
        self-referential value would not terminate."""
        if isinstance(value, dict):
            return {(k if isinstance(k, str) else cls._as_string(k)): cls._value_or_string(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._value_or_string(v) for v in value]
        return cls._as_string(value)

    @classmethod
    def _json_safe(cls, value: Any, *, half: str, action_name: str) -> Any:
        """``value`` when it serializes as a whole, else a copy with the bad parts as strings."""
        try:
            json.dumps(value)
            return value
        except Exception as exc:
            logger.warning(
                "action step value is not JSON-serializable; capturing stringified parts",
                action_name=action_name,
                half=half,
                value_type=type(value).__name__,
                error=repr(exc),
            )
        return cls._stringify_bad_values(value)

    @classmethod
    def _capture_action_step(cls, action_name: str, params: dict[str, Any], result: Any) -> None:
        """Append this action call (name + input + output) to the in-execution step
        buffer so the host runtime can surface every step it ran. A no-op unless capture
        is active (e.g. never inside a sandbox); emit_log suppresses this for its own call.

        The host drains the buffer and may serialize it, so both halves have to be
        JSON-safe. They are normally captured as-is; only if one isn't do we replace the
        bad parts, so an unserializable value costs that value rather than the whole step.
        Both halves are checked, not just the result: an in-process dispatch
        (``ExecutionMode.INLINE``) hands params to the host without serializing them, so
        reaching here is no proof they can be serialized. The whole value is checked with a
        single cheap ``json.dumps`` first, so the happy path stays one call.

        Nothing here may raise into the caller. The action has already succeeded and its
        result is about to be returned; a value that misbehaves while being inspected (a
        mapping whose ``items()`` raises, a ``__str__`` that throws) must cost the log line,
        not the call."""
        try:
            if not capture_active():
                return
            capture_step(
                {
                    "event": "action",
                    "name": action_name,
                    "input": cls._json_safe(params, half="input", action_name=action_name),
                    "output": cls._json_safe(result, half="output", action_name=action_name),
                }
            )
        except Exception as exc:
            logger.warning(
                "could not capture the action step; the action itself is unaffected",
                action_name=action_name,
                error=repr(exc),
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
        execution_mode: ExecutionMode | None,
        action_retry_policy: RetryPolicy | None,
        action_start_to_close_timeout: timedelta | None,
    ) -> Any:
        config = cls._resolve_config(base_url, auth_token)
        # Attach the caller's channel context once here so the platform can inject it
        # into the action's params — individual actions don't each have to send it.
        channel_context = resolve_channel_context()
        return await cls._execute_action(
            action_name=action_name,
            params=params,
            config=config,
            channel_context=channel_context.model_dump(mode="json") if channel_context is not None else None,
            return_type=return_type,
            summary=summary,
            execution_mode=execution_mode,
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
    def _get_action_gateway(cls) -> Callable[..., Any] | None:
        """Return the action gateway registered on ActionsHub, or None if none is."""
        from zamp_public_workflow_sdk.actions_hub import ActionsHub

        return ActionsHub.get_action_gateway()

    @classmethod
    async def _is_registered_locally(cls, action_name: str) -> bool:
        """Whether the action resolves to an action registered in this environment."""
        from zamp_public_workflow_sdk.actions_hub import ActionsHub
        from zamp_public_workflow_sdk.actions_hub.models.core_models import ActionFilter

        actions = await ActionsHub.get_available_actions(ActionFilter(name=action_name))
        return len(actions) > 0

    @classmethod
    async def _execute_action(
        cls,
        action_name: str,
        params: dict[str, Any],
        *,
        config: SdkConfig,
        channel_context: dict[str, Any] | None = None,
        return_type: type | None = None,
        summary: str | None = None,
        execution_mode: ExecutionMode | None = None,
        action_retry_policy: RetryPolicy | None = None,
        action_start_to_close_timeout: timedelta | None = None,
    ) -> Any:
        """Post to ``{config.base_url}/actions`` and return the action's result.

        ``ExecutionMode.INLINE`` asks the platform to run the action inside the POST
        and answer with its terminal state, so the result is read from that one
        response. Anything else is the Temporal path: the POST starts a workflow and
        the result is polled from ``GET /actions/{id}`` until a terminal state.
        """
        client = HttpClient(
            base_url=config.base_url,
            default_headers={"Authorization": f"Bearer {config.auth_token}"},
        )
        inline = execution_mode is ExecutionMode.INLINE

        body: dict = {
            "action_name": action_name,
            "params": params,
            "is_external_action": True,
        }
        if inline:
            body["execution_mode"] = ExecutionMode.INLINE.value
        if action_retry_policy is not None:
            # A policy the caller chose is sent as-is; with INLINE the platform
            # refuses it and says why, which beats dropping it silently here.
            body["retry_policy"] = action_retry_policy.model_dump(mode="json")
        elif not inline:
            # Always send the SDK's retry policy so the server doesn't fall back to
            # its own (longer) default. An inline run is never retried, so it gets none.
            body["retry_policy"] = RetryPolicy.default().model_dump(mode="json")
        if channel_context is not None:
            body["channel_context"] = channel_context
        if summary is not None:
            body["summary"] = summary
        if action_start_to_close_timeout is not None:
            body["start_to_close_timeout_seconds"] = action_start_to_close_timeout.total_seconds()

        response = await cls._post_action(
            client,
            "/actions",
            body,
            inline=inline,
            timeout=cls._inline_request_timeout(action_start_to_close_timeout) if inline else None,
        )
        action_id = response["id"]

        if inline and response.get("status") in TERMINAL_STATUSES:
            result = cls._result_or_raise(response, action_id)
        else:
            # Not inline — or an older platform that dropped the field and answered
            # RUNNING, in which case a version skew costs latency, not correctness.
            poll_timeout = POLL_TIMEOUT_SECONDS
            if action_start_to_close_timeout is not None:
                poll_timeout = max(POLL_TIMEOUT_SECONDS, action_start_to_close_timeout.total_seconds())
            result = await cls._poll_action_result(client, action_id, poll_timeout=poll_timeout)

        if return_type and hasattr(return_type, "model_validate"):
            return return_type.model_validate(result)
        return result

    @staticmethod
    def _inline_request_timeout(action_start_to_close_timeout: timedelta | None) -> float:
        """Total seconds to wait for an inline POST.

        The caller's timeout is clamped to the platform's inline ceiling, since the
        platform clamps the run itself, and a margin is added so the platform's own
        TIMED_OUT answer arrives before this client gives up on the socket.
        """
        requested = (
            action_start_to_close_timeout.total_seconds()
            if action_start_to_close_timeout is not None
            else INLINE_SERVER_MAX_SECONDS
        )
        return min(requested, INLINE_SERVER_MAX_SECONDS) + INLINE_REQUEST_TIMEOUT_MARGIN_SECONDS

    @staticmethod
    def _result_or_raise(data: dict, action_id: str) -> Any:
        """The result of a terminal action document, or the failure it reports, raised.

        Shared by the inline response and the poll loop so both modes raise the same
        error for the same outcome.
        """
        action_status = data["status"]
        if action_status in SUCCESS_STATUSES:
            return data.get("result")
        if action_status in TERMINAL_FAILURE_STATUSES:
            raise RuntimeError(f"Action {action_id} {action_status}: {data.get('error', 'unknown error')}")
        raise RuntimeError(f"Action {action_id} unexpected status: {action_status}")

    @classmethod
    async def _post_action(
        cls,
        client: HttpClient,
        endpoint: str,
        body: dict,
        *,
        inline: bool = False,
        timeout: float | None = None,
        retry_timeout: float = POST_RETRY_TIMEOUT_SECONDS,
    ) -> dict:
        """POST ``body`` to ``endpoint``, retrying transient 5xx with backoff.

        Uses a time-budget + gentle backoff on its OWN conservative constants
        (a create endpoint returning 5xx is already failing — retries must not
        accelerate into it): on a 5xx, keep retrying (backing off) until
        ``retry_timeout`` seconds elapse, so a momentary server error doesn't
        fail the action before it is even created. Non-5xx errors (e.g. 4xx,
        network) propagate immediately.

        An ``inline`` POST is never retried: the action runs inside the request, so
        a 5xx says nothing about whether it already committed, and a retry would
        re-run a non-idempotent write. Its response is an action document whose
        ``error`` field is the action's own failure message, so the envelope check
        is switched off and the document is interpreted by the caller instead.
        """
        interval = POST_RETRY_INITIAL_INTERVAL_SECONDS
        elapsed = 0.0

        while True:
            try:
                return await client.post(
                    endpoint,
                    data=body,
                    timeout=timeout,
                    raise_on_envelope_error=not inline,
                )
            except HttpClientError as exc:
                # Budget exhausted, non-transient, or possibly already run: surface the original error.
                if inline or not cls._is_retryable_5xx(exc) or elapsed >= retry_timeout:
                    raise
                logger.warning(
                    "action POST returned 5xx, retrying",
                    endpoint=endpoint,
                    status_code=exc.status_code,
                    elapsed=elapsed,
                    retry_timeout=retry_timeout,
                    retry_in_seconds=interval,
                )
                await asyncio.sleep(interval)
                elapsed += interval
                interval = cls._next_post_retry_interval(interval)

    @staticmethod
    def _is_retryable_5xx(exc: HttpClientError) -> bool:
        """A 5xx (server-error) response is transient and worth retrying."""
        return exc.status_code is not None and exc.status_code >= 500

    @staticmethod
    def _next_poll_interval(interval: float) -> float:
        """Next poll backoff interval, capped at ``POLL_MAX_INTERVAL_SECONDS``."""
        return min(interval * POLL_BACKOFF_COEFFICIENT, POLL_MAX_INTERVAL_SECONDS)

    @staticmethod
    def _next_post_retry_interval(interval: float) -> float:
        """Next create-retry backoff interval, capped at ``POST_RETRY_MAX_INTERVAL_SECONDS``."""
        return min(interval * POST_RETRY_BACKOFF_COEFFICIENT, POST_RETRY_MAX_INTERVAL_SECONDS)

    @classmethod
    async def _poll_action_result(
        cls,
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
                if not cls._is_retryable_5xx(exc):
                    raise
                logger.warning(
                    "action poll returned 5xx, continuing to poll",
                    action_id=action_id,
                    status_code=exc.status_code,
                    elapsed=elapsed,
                    poll_timeout=poll_timeout,
                )
                interval = cls._next_poll_interval(interval)
                continue

            if data["status"] not in IN_PROGRESS_STATUSES:
                return cls._result_or_raise(data, action_id)
            interval = cls._next_poll_interval(interval)

        raise TimeoutError(f"Action {action_id} did not complete within {poll_timeout}s")
