import asyncio
import json
import os
from datetime import timedelta
from typing import Any, Callable

from zamp_sdk.action_executor.constants import (
    ACTION_ENVELOPE_KEYS,
    IN_PROGRESS_STATUSES,
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
    Route,
)
from zamp_sdk.action_executor.execution_mode import ExecutionMode, resolve_ah_execution_mode
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig
from zamp_sdk.action_executor.utils import HttpClient, HttpClientError
from zamp_sdk.capture import capture_active, capture_step
from zamp_sdk.context import (
    ENV_AUTH_TOKEN,
    ENV_BASE_URL,
    ChannelContext,
    ExecutionHost,
    current_execution_host,
    resolve_channel_context,
)
from zamp_sdk.logger import get_logger
from zamp_sdk.logging.auto import (
    close_action_log,
    fail_action_log,
    open_action_log,
)
from zamp_sdk.logging.constants import NON_LOGGABLE_ACTIONS

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
        log_action: bool | None = None,
    ) -> Any:
        """Run one platform action and return its result.

        ``summary`` doubles as the display title of the log block this call produces — the
        one place to put a human-readable "what this call is doing".

        ``log_action`` decides whether this one call is logged. Three states, not two:

        * ``None`` (default) — follow the run's ``auto_action_logs`` setting.
        * ``True`` — log this call even where the run has logging off.
        * ``False`` — do not log this call even where the run has it on.

        ``None`` is why it is not a plain ``bool``: "I did not say" has to stay distinct from
        "I said no", or a caller could never log one call without configuring the whole run.
        A local in-process call is never logged either way, and ``emit_log`` never is.
        """
        # Resolved before dispatch, not inside it, so one place names every route and one
        # place decides which of them log.
        route, gateway = await cls._resolve_route(action_name)
        try:
            result = await cls._dispatch(
                route=route,
                gateway=gateway,
                log_action=log_action,
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
        except Exception as exc:
            # Captured before the re-raise: the failed call is the one a reader of the log is
            # looking for. The block was already closed as failed by the route that opened it.
            cls._capture_action_step(action_name, params, None, error=exc)
            raise
        cls._capture_action_step(action_name, params, result)
        return result

    @classmethod
    async def _resolve_route(cls, action_name: str) -> tuple[Route, Callable[..., Any] | None]:
        """Which of the three dispatch paths this action takes, and the gateway if it needs one."""
        if current_execution_host() is not ExecutionHost.ACTIONS_HUB:
            return Route.API, None
        gateway = cls._get_action_gateway()
        if gateway is not None and not await cls._is_registered_locally(action_name):
            return Route.GATEWAY, gateway
        return Route.LOCAL_AH, None

    @staticmethod
    def _unwrap_envelope(result: Any) -> Any:
        """The answer inside the gateway's ``{"id", "status", "result", "error"}``.

        A failure shows its ``error`` — the gateway reports one as a *value*, so ``result``
        alone would be ``None`` and lose the reason.

        Display only: the envelope still reaches authored code untouched. The key check is a
        guard, so a response of an unexpected shape is shown whole rather than emptied.
        """
        if isinstance(result, dict) and ACTION_ENVELOPE_KEYS.issubset(result):
            return result.get("error") or result["result"]
        return result

    @classmethod
    async def _dispatch(
        cls,
        *,
        route: Route,
        gateway: Callable[..., Any] | None,
        log_action: bool | None,
        action_name: str,
        params: dict[str, Any],
        base_url: str | None,
        auth_token: str | None,
        summary: str | None,
        return_type: type | None,
        execution_mode: ExecutionMode | None,
        action_retry_policy: RetryPolicy | None,
        action_start_to_close_timeout: timedelta | None,
    ) -> Any:
        """Run the action down the route already resolved for it.

        Each route logs, or does not, for itself: a local call is plumbing on the worker that
        owns the action, so it has no logging code rather than a flag saying not to.
        """
        if route is Route.GATEWAY and gateway is not None:
            return await cls._execute_via_gateway(
                gateway,
                action_name=action_name,
                params=params,
                summary=summary,
                log_action=log_action,
                return_type=return_type,
                action_retry_policy=action_retry_policy,
                action_start_to_close_timeout=action_start_to_close_timeout,
            )
        if route is Route.LOCAL_AH:
            return await cls._execute_via_actions_hub(
                action_name=action_name,
                params=params,
                summary=summary,
                return_type=return_type,
                execution_mode=execution_mode,
                action_retry_policy=action_retry_policy,
                action_start_to_close_timeout=action_start_to_close_timeout,
            )
        return await cls._execute_via_api(
            action_name=action_name,
            params=params,
            base_url=base_url,
            auth_token=auth_token,
            summary=summary,
            log_action=log_action,
            return_type=return_type,
            action_retry_policy=action_retry_policy,
            action_start_to_close_timeout=action_start_to_close_timeout,
        )

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
    def _capture_action_step(
        cls,
        action_name: str,
        params: dict[str, Any],
        result: Any,
        *,
        error: BaseException | None = None,
    ) -> None:
        """Append this action call to the in-execution step buffer so the host runtime can
        surface every step it ran: name + input, then ``output`` or, when the call raised,
        ``error``. A failed call is the one a reader of the log is looking for, so it is
        recorded rather than omitted. A no-op unless capture is active (e.g. never inside a
        sandbox); emit_log suppresses this for its own call.

        The host drains the buffer and may serialize it, so both halves have to be
        JSON-safe. They are normally captured as-is; only if one isn't do we replace the
        bad parts, so an unserializable value costs that value rather than the whole step.
        Both halves are checked, not just the result: an in-process dispatch
        (``ExecutionMode.INLINE``) hands params to the host without serializing them, so
        reaching here is no proof they can be serialized. The whole value is checked with a
        single cheap ``json.dumps`` first, so the happy path stays one call.

        An action in :data:`NON_LOGGABLE_ACTIONS` records nothing: sending a log *is* calling
        one, so it is how the run reports itself rather than a step of the run's work, and the
        same reasoning that keeps it out of the live message keeps it out of the file.

        Nothing here may raise into the caller. The action has already succeeded and its
        result is about to be returned; a value that misbehaves while being inspected (a
        mapping whose ``items()`` raises, a ``__str__`` that throws) must cost the log line,
        not the call."""
        try:
            if action_name in NON_LOGGABLE_ACTIONS or not capture_active():
                return
            entry: dict[str, Any] = {
                "event": "action",
                "name": action_name,
                "input": cls._json_safe(params, half="input", action_name=action_name),
            }
            if error is not None:
                entry["error"] = cls._as_string(error)
            else:
                entry["output"] = cls._json_safe(result, half="output", action_name=action_name)
            capture_step(entry)
        except Exception as exc:
            logger.warning(
                "could not capture the action step; the action itself is unaffected",
                action_name=action_name,
                error=repr(exc),
            )

    @classmethod
    async def _execute_via_gateway(
        cls,
        gateway: Callable[..., Any],
        *,
        action_name: str,
        params: dict[str, Any],
        summary: str | None,
        log_action: bool | None,
        return_type: type | None,
        action_retry_policy: RetryPolicy | None,
        action_start_to_close_timeout: timedelta | None,
    ) -> Any:
        """Hand the action to the host's gateway, showing the call in the live message.

        Returns the gateway's envelope unchanged — only the block is unwrapped.
        """
        block_id = await open_action_log(action_name, params, summary=summary, log_action=log_action)
        try:
            result = await gateway(
                action_name,
                params,
                summary=summary,
                return_type=return_type,
                action_retry_policy=action_retry_policy,
                action_start_to_close_timeout=action_start_to_close_timeout,
            )
        except Exception as exc:
            await fail_action_log(block_id, action_name, exc)
            raise
        await close_action_log(block_id, action_name, cls._unwrap_envelope(result))
        return result

    @staticmethod
    def _can_emit(config: SdkConfig, channel_context: ChannelContext | None) -> bool:
        """Whether a block for this call can be shown, and shown in the right place.

        An emit is its own API call, dispatched with no arguments, so it resolves credentials
        from the environment and needs a channel to appear in. Two things follow.

        A process with neither — someone driving the SDK from their own program, who passed
        credentials to ``execute`` and is not inside a Zamp run — has nowhere to put a block, so
        the call goes unlogged rather than failing an emit for every action.

        And the environment has to be the *same* deployment the action went to. A caller can
        point ``execute`` at one tenant while the ambient credentials name another; the emit
        would follow the ambient ones and carry this action's input and result there. Compared
        rather than merely required, so logs cannot cross that boundary — but compared the way
        the URL is *used*, with the trailing slash stripped as ``_build_url`` strips it, so a
        formatting difference does not read as a different deployment and quietly stop logging.
        """
        ambient_url = (os.environ.get(ENV_BASE_URL) or "").rstrip("/")
        return (
            channel_context is not None
            and bool(ambient_url)
            and config.base_url.rstrip("/") == ambient_url
            and config.auth_token == os.environ.get(ENV_AUTH_TOKEN)
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
        log_action: bool | None,
        return_type: type | None,
        action_retry_policy: RetryPolicy | None,
        action_start_to_close_timeout: timedelta | None,
    ) -> Any:
        """Call the platform over HTTP, showing the call in the live message.

        No unwrapping: this route returns the action's own answer, and a terminal failure
        raises rather than coming back as a value.
        """
        config = cls._resolve_config(base_url, auth_token)
        # Attach the caller's channel context once here so the platform can inject it
        # into the action's params — individual actions don't each have to send it.
        channel_context = resolve_channel_context()
        block_id = (
            await open_action_log(action_name, params, summary=summary, log_action=log_action)
            if cls._can_emit(config, channel_context)
            else None
        )
        try:
            result = await cls._execute_action(
                action_name=action_name,
                params=params,
                config=config,
                channel_context=channel_context.model_dump(mode="json") if channel_context is not None else None,
                return_type=return_type,
                summary=summary,
                action_retry_policy=action_retry_policy,
                action_start_to_close_timeout=action_start_to_close_timeout,
            )
        except Exception as exc:
            await fail_action_log(block_id, action_name, exc)
            raise
        await close_action_log(block_id, action_name, result)
        return result

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
        if channel_context is not None:
            body["channel_context"] = channel_context
        if summary is not None:
            body["summary"] = summary
        if action_start_to_close_timeout is not None:
            body["start_to_close_timeout_seconds"] = action_start_to_close_timeout.total_seconds()

        response = await cls._post_action(client, "/actions", body)
        action_id = response["id"]
        poll_timeout = POLL_TIMEOUT_SECONDS
        if action_start_to_close_timeout is not None:
            poll_timeout = max(POLL_TIMEOUT_SECONDS, action_start_to_close_timeout.total_seconds())
        result = await cls._poll_action_result(client, action_id, poll_timeout=poll_timeout)

        if return_type and hasattr(return_type, "model_validate"):
            return return_type.model_validate(result)
        return result

    @classmethod
    async def _post_action(
        cls,
        client: HttpClient,
        endpoint: str,
        body: dict,
        *,
        retry_timeout: float = POST_RETRY_TIMEOUT_SECONDS,
    ) -> dict:
        """POST ``body`` to ``endpoint``, retrying transient 5xx with backoff.

        Uses a time-budget + gentle backoff on its OWN conservative constants
        (a create endpoint returning 5xx is already failing — retries must not
        accelerate into it): on a 5xx, keep retrying (backing off) until
        ``retry_timeout`` seconds elapse, so a momentary server error doesn't
        fail the action before it is even created. Non-5xx errors (e.g. 4xx,
        network) propagate immediately.
        """
        interval = POST_RETRY_INITIAL_INTERVAL_SECONDS
        elapsed = 0.0

        while True:
            try:
                return await client.post(endpoint, data=body)
            except HttpClientError as exc:
                # Budget exhausted or non-transient: surface the original error.
                if not cls._is_retryable_5xx(exc) or elapsed >= retry_timeout:
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

            action_status = data["status"]

            if action_status in SUCCESS_STATUSES:
                return data.get("result")
            if action_status in TERMINAL_FAILURE_STATUSES:
                raise RuntimeError(f"Action {action_id} {action_status}: {data.get('error', 'unknown error')}")
            if action_status not in IN_PROGRESS_STATUSES:
                raise RuntimeError(f"Action {action_id} unexpected status: {action_status}")
            interval = cls._next_poll_interval(interval)

        raise TimeoutError(f"Action {action_id} did not complete within {poll_timeout}s")
