"""The execution host is the single switch that decides both transport and context source.

Two runtimes exist in practice and neither configures the other's mechanism: the
zamp-executor declares ``ACTIONS_HUB`` and binds a context in-process, while a sandbox (and
any external caller) leaves the default ``API`` and is fed ``ZAMP_*`` environment variables.
These tests pin the whole matrix, including the combinations that only arise by mistake or
by sandboxed code binding a context it was not given.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.context import (
    ChannelContext,
    ChannelType,
    ExecutionHost,
    bind_channel_context,
    clear_channel_context,
    current_execution_host,
    resolve_channel_context,
)
from zamp_sdk.logging.logging import _current_tool_call_id, _emit_context

_HOST = "ZAMP_SDK_EXECUTION_HOST"
_ENV_VARS = (
    "ZAMP_CHANNEL_TYPE",
    "ZAMP_CHANNEL_ID",
    "ZAMP_STREAMING_ID",
    "ZAMP_MESSAGE_ID",
    "ZAMP_TOOL_CALL_ID",
    "ZAMP_RUN_ID",
    "ZAMP_BASE_URL",
    "ZAMP_AUTH_TOKEN",
)

_ENV_CHANNEL_ID = uuid.uuid4()
_BOUND_CHANNEL_ID = uuid.uuid4()


def _full_env(channel_id: uuid.UUID = _ENV_CHANNEL_ID) -> dict[str, str]:
    """A complete injected context, as a runtime hands one to a sandbox."""
    return {
        "ZAMP_CHANNEL_TYPE": "conversation",
        "ZAMP_CHANNEL_ID": str(channel_id),
        "ZAMP_STREAMING_ID": "env-stream",
        "ZAMP_MESSAGE_ID": "env-message",
        "ZAMP_TOOL_CALL_ID": "env-tool-call",
        "ZAMP_RUN_ID": "env-run",
    }


def _bound(channel_id: uuid.UUID = _BOUND_CHANNEL_ID) -> ChannelContext:
    return ChannelContext(
        channel_type=ChannelType.TASK,
        channel_id=channel_id,
        streaming_id="bound-stream",
        message_id="bound-message",
        tool_call_id="bound-tool-call",
        run_id="bound-run",
    )


@pytest.fixture(autouse=True)
def _clean_slate(monkeypatch):
    """No host declared, no injected context, nothing bound — the state an external caller
    starts in. Each test opts into whatever it needs."""
    for var in (_HOST, *_ENV_VARS):
        monkeypatch.delenv(var, raising=False)
    clear_channel_context()
    yield
    clear_channel_context()


class TestHostResolution:
    def test_an_undeclared_host_is_the_api(self):
        assert current_execution_host() is ExecutionHost.API

    @pytest.mark.parametrize("value", ["", " ", "\t", "\n"])
    def test_a_blank_declaration_is_the_api(self, monkeypatch, value):
        monkeypatch.setenv(_HOST, value)
        assert current_execution_host() is ExecutionHost.API

    @pytest.mark.parametrize("value", ["api", "API", "Api", "  api  "])
    def test_api_is_accepted_in_any_casing(self, monkeypatch, value):
        monkeypatch.setenv(_HOST, value)
        assert current_execution_host() is ExecutionHost.API

    @pytest.mark.parametrize("value", ["actions_hub", "ACTIONS_HUB", "Actions_Hub", " actions_hub "])
    def test_actions_hub_is_accepted_in_any_casing(self, monkeypatch, value):
        monkeypatch.setenv(_HOST, value)
        assert current_execution_host() is ExecutionHost.ACTIONS_HUB

    @pytest.mark.parametrize("value", ["actionshub", "actions-hub", "hub", "temporal", "true", "1", "none", "api x"])
    def test_an_unknown_host_raises_instead_of_defaulting(self, monkeypatch, value):
        """Falling back would silently change *both* transport and context source, so a typo
        has to fail loudly rather than send actions somewhere the caller did not intend."""
        monkeypatch.setenv(_HOST, value)
        with pytest.raises(ValueError, match="not a known execution host"):
            current_execution_host()

    def test_the_error_names_the_variable_and_the_valid_values(self, monkeypatch):
        monkeypatch.setenv(_HOST, "hub")
        with pytest.raises(ValueError) as exc:
            current_execution_host()
        assert _HOST in str(exc.value)
        assert "actions_hub" in str(exc.value) and "api" in str(exc.value)

    def test_the_host_is_read_per_call_not_cached(self, monkeypatch):
        """A cached value would make the two runtimes' behaviour depend on import order."""
        monkeypatch.setenv(_HOST, "actions_hub")
        assert current_execution_host() is ExecutionHost.ACTIONS_HUB
        monkeypatch.setenv(_HOST, "api")
        assert current_execution_host() is ExecutionHost.API


class TestChannelContextSource:
    """``resolve_channel_context`` — what the API request body carries."""

    def test_api_host_reads_the_injected_context(self, monkeypatch):
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)

        ctx = resolve_channel_context()

        assert ctx is not None
        assert ctx.channel_id == _ENV_CHANNEL_ID
        assert ctx.channel_type is ChannelType.CONVERSATION
        assert ctx.streaming_id == "env-stream"

    def test_api_host_with_nothing_injected_resolves_to_none(self):
        assert resolve_channel_context() is None

    @pytest.mark.parametrize("drop", ["ZAMP_CHANNEL_ID", "ZAMP_RUN_ID", "ZAMP_STREAMING_ID"])
    def test_api_host_with_a_partial_context_resolves_to_none(self, monkeypatch, drop):
        """Every field is required, so a half-injected context is not a context. Better None
        than a half-built one that attaches output to the wrong place."""
        env = _full_env()
        env.pop(drop)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        assert resolve_channel_context() is None

    def test_api_host_with_an_unparseable_channel_id_resolves_to_none(self, monkeypatch):
        env = _full_env()
        env["ZAMP_CHANNEL_ID"] = "not-a-uuid"
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        assert resolve_channel_context() is None

    def test_api_host_with_an_unknown_channel_type_resolves_to_none(self, monkeypatch):
        env = _full_env()
        env["ZAMP_CHANNEL_TYPE"] = "slack"
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        assert resolve_channel_context() is None

    def test_api_host_ignores_a_bound_context_entirely(self):
        """The security-relevant case. Inside a sandbox imports work, so the code being run
        can call bind_channel_context itself; on the API path that value must never be
        consulted or it could redirect its own output to another channel."""
        bind_channel_context(_bound())

        assert resolve_channel_context() is None

    def test_api_host_prefers_the_injected_context_over_a_bound_one(self, monkeypatch):
        """Same property when both exist: the runtime's injected context wins."""
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)
        bind_channel_context(_bound())

        ctx = resolve_channel_context()

        assert ctx is not None
        assert ctx.channel_id == _ENV_CHANNEL_ID

    def test_actions_hub_host_reads_the_bound_context(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        bind_channel_context(_bound())

        ctx = resolve_channel_context()

        assert ctx is not None
        assert ctx.channel_id == _BOUND_CHANNEL_ID
        assert ctx.channel_type is ChannelType.TASK

    def test_actions_hub_host_with_nothing_bound_resolves_to_none(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")

        assert resolve_channel_context() is None

    def test_actions_hub_host_ignores_injected_env(self, monkeypatch):
        """The executor sets no ZAMP_* vars, but if a pod ever did they must not shadow the
        context the running workflow bound for this execution."""
        monkeypatch.setenv(_HOST, "actions_hub")
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)

        assert resolve_channel_context() is None

    def test_actions_hub_host_prefers_the_bound_context_over_injected_env(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)
        bind_channel_context(_bound())

        ctx = resolve_channel_context()

        assert ctx is not None
        assert ctx.channel_id == _BOUND_CHANNEL_ID

    def test_clearing_the_bound_context_resolves_to_none(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        bind_channel_context(_bound())
        clear_channel_context()

        assert resolve_channel_context() is None

    def test_rebinding_replaces_the_previous_context(self, monkeypatch):
        """Each execution binds at run start; the second must not see the first's."""
        monkeypatch.setenv(_HOST, "actions_hub")
        first, second = uuid.uuid4(), uuid.uuid4()
        bind_channel_context(_bound(first))
        bind_channel_context(_bound(second))

        ctx = resolve_channel_context()

        assert ctx is not None and ctx.channel_id == second

    def test_an_unknown_host_raises_rather_than_guessing_a_source(self, monkeypatch):
        monkeypatch.setenv(_HOST, "hub")
        with pytest.raises(ValueError):
            resolve_channel_context()


class TestEmitContextSource:
    """``_emit_context`` — the ``context`` field on the emit_log payload."""

    def test_api_host_emits_the_injected_context(self, monkeypatch):
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)

        assert _emit_context() == {
            "channel_type": "conversation",
            "channel_id": str(_ENV_CHANNEL_ID),
            "streaming_id": "env-stream",
            "message_id": "env-message",
            "tool_call_id": "env-tool-call",
            "run_id": "env-run",
        }

    def test_api_host_emits_only_the_keys_that_are_set(self, monkeypatch):
        """A partial env is still usable here — unlike a ChannelContext, the emit payload
        is a flat dict, so an unset variable simply isn't sent."""
        monkeypatch.setenv("ZAMP_CHANNEL_ID", str(_ENV_CHANNEL_ID))
        monkeypatch.setenv("ZAMP_RUN_ID", "env-run")

        assert _emit_context() == {"channel_id": str(_ENV_CHANNEL_ID), "run_id": "env-run"}

    def test_api_host_emits_an_empty_context_when_nothing_is_injected(self):
        assert _emit_context() == {}

    def test_api_host_ignores_a_bound_context(self):
        bind_channel_context(_bound())

        assert _emit_context() == {}

    def test_actions_hub_host_emits_the_bound_context(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        bind_channel_context(_bound())

        emitted = _emit_context()

        assert emitted["channel_id"] == str(_BOUND_CHANNEL_ID)
        assert emitted["channel_type"] == "task"
        assert emitted["streaming_id"] == "bound-stream"

    def test_actions_hub_host_emits_an_empty_context_when_nothing_is_bound(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)

        assert _emit_context() == {}


class TestToolCallIdSource:
    """``_current_tool_call_id`` — what emitted blocks are parented under."""

    def test_api_host_uses_the_injected_tool_call_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "env-tool-call")

        assert _current_tool_call_id() == "env-tool-call"

    def test_api_host_ignores_a_bound_tool_call_id(self):
        bind_channel_context(_bound())

        assert _current_tool_call_id() is None

    def test_actions_hub_host_uses_the_bound_tool_call_id(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "env-tool-call")
        bind_channel_context(_bound())

        assert _current_tool_call_id() == "bound-tool-call"

    def test_actions_hub_host_with_nothing_bound_has_no_parent(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "env-tool-call")

        assert _current_tool_call_id() is None


@pytest.mark.asyncio
class TestDispatchByHost:
    """The same switch decides the transport."""

    async def test_undeclared_host_dispatches_over_http(self):
        with (
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as hub,
        ):
            api.return_value = "api"
            await ActionExecutor.execute("action", {})

        api.assert_awaited_once()
        hub.assert_not_called()

    async def test_actions_hub_host_with_no_gateway_dispatches_in_process(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        with (
            patch.object(ActionExecutor, "_get_action_gateway", return_value=None),
            patch.object(ActionExecutor, "_execute_via_api", new_callable=AsyncMock) as api,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as hub,
        ):
            hub.return_value = "hub"
            await ActionExecutor.execute("action", {})

        hub.assert_awaited_once()
        api.assert_not_called()

    async def test_actions_hub_host_routes_an_unregistered_action_to_the_gateway(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        gateway = AsyncMock(return_value="gateway")
        with (
            patch.object(ActionExecutor, "_get_action_gateway", return_value=gateway),
            patch.object(ActionExecutor, "_is_registered_locally", new_callable=AsyncMock) as local,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as hub,
        ):
            local.return_value = False
            result = await ActionExecutor.execute("remote_action", {})

        assert result == "gateway"
        gateway.assert_awaited_once()
        hub.assert_not_called()

    async def test_actions_hub_host_keeps_a_locally_registered_action_in_process(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        gateway = AsyncMock(return_value="gateway")
        with (
            patch.object(ActionExecutor, "_get_action_gateway", return_value=gateway),
            patch.object(ActionExecutor, "_is_registered_locally", new_callable=AsyncMock) as local,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as hub,
        ):
            local.return_value = True
            hub.return_value = "hub"
            result = await ActionExecutor.execute("local_action", {})

        assert result == "hub"
        gateway.assert_not_called()

    async def test_an_unknown_host_fails_the_call(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actionshub")
        with pytest.raises(ValueError, match="not a known execution host"):
            await ActionExecutor.execute("action", {})


@pytest.mark.asyncio
class TestPayloadsEndToEnd:
    """What actually reaches the wire, rather than what the helpers return."""

    async def test_api_host_attaches_the_injected_context_to_the_request_body(self, monkeypatch):
        for k, v in _full_env().items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("ZAMP_BASE_URL", "https://api.zamp.test")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "tok")

        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as post:
            post.return_value = "ok"
            await ActionExecutor.execute("action", {"p": 1})

        sent = post.call_args.kwargs["channel_context"]
        assert sent["channel_id"] == str(_ENV_CHANNEL_ID)
        assert sent["channel_type"] == "conversation"

    async def test_api_host_sends_no_context_when_only_a_bound_one_exists(self, monkeypatch):
        """End-to-end form of the redirect guard: a bound context must not reach the wire."""
        monkeypatch.setenv("ZAMP_BASE_URL", "https://api.zamp.test")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "tok")
        bind_channel_context(_bound())

        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as post:
            post.return_value = "ok"
            await ActionExecutor.execute("action", {})

        assert post.call_args.kwargs["channel_context"] is None

    async def test_actions_hub_host_never_builds_a_request_body(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        bind_channel_context(_bound())

        with (
            patch.object(ActionExecutor, "_get_action_gateway", return_value=None),
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as post,
            patch.object(ActionExecutor, "_execute_via_actions_hub", new_callable=AsyncMock) as hub,
        ):
            hub.return_value = "hub"
            await ActionExecutor.execute("action", {})

        post.assert_not_called()
        hub.assert_awaited_once()


@pytest.mark.asyncio
class TestBoundContextIsolation:
    """The bound context is a ContextVar, so it is per-task. The executor relies on this to
    keep concurrent executions on one worker from seeing each other's channel."""

    async def test_a_sibling_task_does_not_see_a_bound_context(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        seen: dict[str, object] = {}

        async def binder():
            bind_channel_context(_bound())
            seen["binder"] = resolve_channel_context()

        async def sibling():
            seen["sibling"] = resolve_channel_context()

        await asyncio.gather(asyncio.create_task(binder()), asyncio.create_task(sibling()))

        assert seen["binder"] is not None
        assert seen["sibling"] is None

    async def test_two_concurrent_executions_keep_their_own_context(self, monkeypatch):
        monkeypatch.setenv(_HOST, "actions_hub")
        first, second = uuid.uuid4(), uuid.uuid4()
        seen: dict[uuid.UUID, object] = {}

        async def run(channel_id: uuid.UUID, delay: float):
            bind_channel_context(_bound(channel_id))
            await asyncio.sleep(delay)
            ctx = resolve_channel_context()
            seen[channel_id] = ctx.channel_id if ctx else None

        await asyncio.gather(
            asyncio.create_task(run(first, 0.02)),
            asyncio.create_task(run(second, 0.0)),
        )

        assert seen[first] == first
        assert seen[second] == second

    async def test_a_child_task_inherits_the_binding(self, monkeypatch):
        """Authored code awaits helpers inside its own task tree, so the context has to
        survive into children even though it must not leak sideways."""
        monkeypatch.setenv(_HOST, "actions_hub")
        bind_channel_context(_bound())

        async def child():
            ctx = resolve_channel_context()
            return ctx.channel_id if ctx else None

        assert await asyncio.create_task(child()) == _BOUND_CHANNEL_ID
