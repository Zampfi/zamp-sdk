"""The SDK's own logging of action calls.

The rules worth pinning down are the ones that are wrong in a way nobody notices until a
customer sees it: a script that already logs its own calls must not end up showing two blocks,
and a block that opens must always close.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import LOGGED_ROUTES, Route
from zamp_sdk.logging import log_control
from zamp_sdk.logging.auto import (
    close_action_log,
    fail_action_log,
    open_action_log,
    unwrap_result,
)
from zamp_sdk.logging.constants import EMIT_LOG_ACTION_NAME
from zamp_sdk.logging.log_control import configure_auto_action_logs


class _Emits:
    """Records what the auto-logger emitted, without going near the platform."""

    def __init__(self):
        self.uses: list[tuple] = []
        self.results: list[tuple] = []
        self.texts: list[str] = []

    async def tool_use(self, name, *, display_title=None, input=None, id=None, auto=False):
        self.uses.append((name, display_title, input, auto))
        return f"emit_{len(self.uses)}"

    async def tool_result(self, block_id, content, *, name=None, auto=False):
        self.results.append((block_id, content, name, auto))

    async def text(self, content):
        self.texts.append(content)


@pytest.fixture(autouse=True)
def _auto_logging_on():
    """These tests are about what the auto-logger does, so it has to be switched on. The
    shared conftest leaves it at its shipped default, which is off."""
    configure_auto_action_logs(True)


@pytest.fixture
def emits():
    """Patched on ``auto``, not on ``logging`` where they are defined.

    ``auto`` imports the helpers by name at module load, so it holds its own reference and
    replacing the attribute on the defining module would not reach it.
    """
    recorder = _Emits()
    with (
        patch("zamp_sdk.logging.auto.emit_tool_use", recorder.tool_use),
        patch("zamp_sdk.logging.auto.emit_tool_result", recorder.tool_result),
        patch("zamp_sdk.logging.logging.emit_text", recorder.text),
    ):
        yield recorder


async def _run(action="do_thing", *, params=None, summary=None, should_log=True, log_action=None):
    """One successful action call, logged the way ``execute`` logs it."""
    block_id = await open_action_log(
        action, params or {}, summary=summary, should_log=should_log, log_action=log_action
    )
    await close_action_log(block_id, action, {"ok": True})
    return block_id


class TestWhenItLogs:
    @pytest.mark.asyncio
    async def test_logs_a_pair_around_the_call(self, emits):
        await _run(summary="Fetching invoice INV-1")

        assert emits.uses == [("do_thing", "Fetching invoice INV-1", {}, True)]
        assert len(emits.results) == 1
        assert emits.results[0][2] == "do_thing"

    @pytest.mark.asyncio
    async def test_summary_becomes_the_display_title(self, emits):
        """The author's one-line description of the call is what the user reads, so it has to
        reach the block rather than being left to the raw action name."""
        await _run(summary="Reconciling 12 invoices for ACME")
        assert emits.uses[0][1] == "Reconciling 12 invoices for ACME"

    @pytest.mark.asyncio
    async def test_emits_are_marked_auto(self, emits):
        """Marked, so the SDK's own blocks do not mark the next call as hand-logged. That mark
        means a human wrote the emit."""
        await _run()
        assert emits.uses[0][3] is True
        assert emits.results[0][3] is True

    @pytest.mark.asyncio
    async def test_does_not_log_a_local_actions_hub_call(self, emits):
        await _run(should_log=False)
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_does_not_log_emit_log_itself(self, emits):
        """The logger logging itself is unbounded recursion, not a duplicate."""
        await _run(action="emit_log")
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_off_by_default(self, emits):
        log_control._config.set(None)
        await _run()
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_the_platform_config_from_the_environment_turns_it_on(self, emits, monkeypatch):
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "true")
        await _run()
        assert len(emits.uses) == 1


class TestExplicitOverride:
    @pytest.mark.asyncio
    async def test_log_action_false_silences_a_call_that_would_log(self, emits):
        await _run(log_action=False)
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_log_action_true_logs_even_with_auto_off(self, emits):
        configure_auto_action_logs(False)
        await _run(log_action=True)
        assert len(emits.uses) == 1

    @pytest.mark.asyncio
    async def test_log_action_never_overrides_the_recursion_guard(self, emits):
        """An override is the author's preference; recursion is a defect. Preference loses."""
        await _run(action="emit_log", log_action=True)
        assert emits.uses == []


class TestPairing:
    @pytest.mark.asyncio
    async def test_a_failing_action_still_closes_its_block(self, emits):
        """An unclosed tool_use renders as running forever."""
        block_id = await open_action_log("do_thing", {})
        await fail_action_log(block_id, "do_thing", RuntimeError("upstream down"))

        assert len(emits.uses) == 1
        assert len(emits.results) == 1
        assert "upstream down" in emits.results[0][1]

    @pytest.mark.asyncio
    async def test_a_call_that_was_not_logged_emits_neither_half(self, emits):
        """Half-suppression is worse than none: a result would dangle against an id that was
        never announced. The None block id is what rules that out."""
        block_id = await open_action_log("do_thing", {}, should_log=False)
        assert block_id is None

        await fail_action_log(block_id, "do_thing", RuntimeError("boom"))
        await close_action_log(block_id, "do_thing", {"ok": True})

        assert emits.uses == []
        assert emits.results == []

    @pytest.mark.asyncio
    async def test_a_broken_emit_does_not_break_the_action(self):
        """Logging is telemetry wrapped around somebody's real work. It may lose the line; it
        may not lose the work."""
        with patch(
            "zamp_sdk.logging.auto.emit_tool_use",
            new=AsyncMock(side_effect=RuntimeError("emit broke")),
        ):
            block_id = await open_action_log("do_thing", {})

        assert block_id is None, "a failed open leaves nothing to close"
        await close_action_log(block_id, "do_thing", {"ok": True})


class TestRouting:
    @pytest.mark.asyncio
    async def test_api_host_routes_to_the_api(self):
        with patch(
            "zamp_sdk.action_executor.action_executor.current_execution_host",
            return_value=__import__("zamp_sdk.context", fromlist=["ExecutionHost"]).ExecutionHost.API,
        ):
            route, gateway = await ActionExecutor._resolve_route("do_thing")
        assert route is Route.API
        assert gateway is None

    @pytest.mark.asyncio
    async def test_an_action_registered_locally_is_not_logged(self):
        """It is an in-process call on the worker that owns the action — plumbing, not a tool
        call the user is waiting on."""
        assert Route.LOCAL_AH not in LOGGED_ROUTES
        assert Route.API in LOGGED_ROUTES
        assert Route.GATEWAY in LOGGED_ROUTES


class TestItCostsNothingWhenOff:
    """This runs inside every action call, in sandbox scripts and in workflows. When logging
    is off it must be a cheap check and nothing else."""

    @pytest.mark.asyncio
    async def test_no_emit_is_attempted(self, emits):
        configure_auto_action_logs(False)
        assert await open_action_log("do_thing", {"a": 1}) is None
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_closing_an_unlogged_call_is_a_no_op(self, emits):
        await close_action_log(None, "do_thing", {"ok": True})
        await fail_action_log(None, "do_thing", RuntimeError("boom"))
        assert emits.results == []


class TestTheEmitPathCannotRecurse:
    """Sending a log is itself an action call, so logging that call would log forever. The
    name list is the only thing preventing it, which is why it has a test of its own."""

    @pytest.mark.asyncio
    async def test_the_emit_action_is_never_logged(self, emits):
        assert await open_action_log(EMIT_LOG_ACTION_NAME, {}) is None
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_not_even_when_a_caller_explicitly_asks(self, emits):
        """An override is the author's preference; recursion is a defect. Preference loses."""
        assert await open_action_log(EMIT_LOG_ACTION_NAME, {}, log_action=True) is None
        assert emits.uses == []

    @pytest.mark.asyncio
    async def test_a_real_auto_logged_call_dispatches_exactly_two_emits(self):
        """The end of the argument: one action call produces one pair and stops. If the emit
        path ever grew a second action call this would run away, and it is what would catch it."""
        dispatched: list = []

        async def record(name, params, **kwargs):
            dispatched.append(name)
            return {}

        with patch("zamp_sdk.action_executor.ActionExecutor.execute", new=record):
            block_id = await open_action_log("do_thing", {"a": 1}, summary="Doing")
            await close_action_log(block_id, "do_thing", {"ok": True})

        assert dispatched == [EMIT_LOG_ACTION_NAME, EMIT_LOG_ACTION_NAME]


class TestTheResultShown:
    """A gateway call arrives wrapped in a transport envelope; only the answer is shown."""

    @pytest.mark.parametrize(
        ("returned", "shown"),
        [
            (
                {"id": "external-action-executor-0d95", "status": "COMPLETED", "result": {"datasets": []}},
                {"datasets": []},
            ),
            # The API route already unwraps, so its value passes through untouched.
            ({"datasets": []}, {"datasets": []}),
            # A failed call reports failure as a value, not an exception, so this runs on the
            # success path — show the reason rather than the None it left in ``result``.
            (
                {"id": "x", "status": "FAILED", "result": None, "error": "Action not found"},
                "Action not found",
            ),
            # Not an envelope: an action whose own output has a result key keeps all of it.
            ({"result": 1, "status": "ok"}, {"result": 1, "status": "ok"}),
            ("a string", "a string"),
            (None, None),
        ],
    )
    def test_the_envelope_is_stripped_but_nothing_else_is(self, returned, shown):
        assert unwrap_result(returned) == shown

    @pytest.mark.asyncio
    async def test_the_block_is_closed_with_the_unwrapped_result(self):
        envelope = {"id": "x", "status": "COMPLETED", "result": {"rows": 3}}

        with patch("zamp_sdk.logging.auto.emit_tool_result", new=AsyncMock()) as emit:
            await close_action_log("block-1", "agent_db_query", envelope)

        assert emit.await_args.args[1] == {"rows": 3}, "the id and status are plumbing"
