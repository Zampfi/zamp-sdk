"""What ``ActionExecutor.execute`` records and shows for each call it runs.

Three things meet at this seam: the step buffer that becomes the run's log file, the spawned
task ids a caller needs to list, and the live log blocks. They are tested together because the
bug worth catching is one of them changing the others.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import configure_auto_action_logs
from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.capture import drain_log_capture, start_log_capture
from zamp_sdk.logging.constants import EMIT_LOG_ACTION_NAME
from zamp_sdk.logging.models import EmitLogResult
from zamp_sdk.version import __version__

_MODULE = "zamp_sdk.action_executor.action_executor"


def _tool_use_blocks(run) -> list:
    """Display titles of every ``tool_use`` block that reached the platform via ``dispatch``.

    Counts what the user would actually see, rather than which helper happened to be called.
    """
    titles = []
    for call in run.await_args_list:
        if call.kwargs.get("action_name") != "emit_log":
            continue
        block = call.kwargs.get("params", {}).get("block", {})
        if block.get("type") == "tool_use":
            titles.append(block.get("display_title"))
    return titles


@pytest.fixture(autouse=True)
def _runtime_env(monkeypatch):
    """What the runtime gives a sandbox process: credentials for the call, and a channel for
    the blocks. The API route logs nothing without both."""
    monkeypatch.setenv("ZAMP_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ZAMP_AUTH_TOKEN", "token")
    monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
    monkeypatch.setenv("ZAMP_CHANNEL_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("ZAMP_STREAMING_ID", "s")
    monkeypatch.setenv("ZAMP_MESSAGE_ID", "m")
    monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "t")
    monkeypatch.setenv("ZAMP_RUN_ID", "r")


class TestFailureCapture:
    """A step log that records only the calls that worked omits exactly the one a reader of
    a failed run is looking for."""

    def test_a_failed_call_is_recorded_with_its_error(self):
        start_log_capture()
        ActionExecutor._capture_action_step("do_thing", {"a": 1}, None, error=RuntimeError("upstream down"))
        assert drain_log_capture() == [
            {
                "sdk_version": __version__,
                "event": "action",
                "name": "do_thing",
                "input": {"a": 1},
                "error": "upstream down",
            }
        ]

    def test_a_failed_call_records_no_output_key(self):
        """``output: None`` and "it failed" are different facts and must not look alike."""
        start_log_capture()
        ActionExecutor._capture_action_step("do_thing", {}, None, error=ValueError("bad"))
        (entry,) = drain_log_capture()
        assert "output" not in entry

    def test_a_successful_call_records_no_error_key(self):
        start_log_capture()
        ActionExecutor._capture_action_step("do_thing", {}, {"ok": True})
        (entry,) = drain_log_capture()
        assert "error" not in entry
        assert entry["output"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_a_raising_action_is_captured_and_still_raises(self):
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.side_effect = RuntimeError("boom")
            with pytest.raises(RuntimeError, match="boom"):
                await ActionExecutor.execute("do_thing", {"a": 1})

        (entry,) = drain_log_capture()
        assert entry["name"] == "do_thing"
        assert entry["error"] == "boom"


class TestTheEmittedBlocks:
    @pytest.mark.asyncio
    async def test_an_api_call_logs_itself(self):
        configure_auto_action_logs(True)
        with (
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run,
            patch("zamp_sdk.logging.auto._emit_tool_use_block", new_callable=AsyncMock) as use,
            patch("zamp_sdk.logging.auto.emit_tool_result", new_callable=AsyncMock) as result,
        ):
            run.return_value = {"ok": True}
            use.return_value = ("emit_1", EmitLogResult(ok=True))
            await ActionExecutor.execute("do_thing", {"a": 1}, summary="Doing the thing")

        assert use.await_count == 1
        assert use.await_args.kwargs["display_title"] == "Doing the thing"
        assert result.await_count == 1

    @pytest.mark.asyncio
    async def test_parallel_calls_each_get_their_own_pair(self):
        """A fan-out is the shape that would expose shared state in the auto-logger: four
        concurrent calls must produce four independent pairs, not blocks that interleave into
        each other. The sleeps make the interleaving real rather than four sequential runs
        that happen to be written as a gather."""
        configure_auto_action_logs(True)

        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = {"ok": True}

            async def branch(i: int) -> None:
                await asyncio.sleep(0.01 * i)
                await ActionExecutor.execute("do_thing", {"i": i}, summary=f"Item {i}")

            await asyncio.gather(*(branch(i) for i in range(4)))

        assert sorted(_tool_use_blocks(run)) == [
            "Item 0",
            "Item 1",
            "Item 2",
            "Item 3",
        ], "one block per call, each carrying its own summary"

    @pytest.mark.asyncio
    async def test_the_action_still_runs_when_logging_is_broken(self):
        configure_auto_action_logs(True)
        with (
            patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run,
            patch(
                "zamp_sdk.logging.auto._emit_tool_use_block",
                new=AsyncMock(side_effect=RuntimeError("emit broke")),
            ),
        ):
            run.return_value = {"ok": True}
            assert await ActionExecutor.execute("do_thing", {}) == {"ok": True}


class TestTheEmitActionLeavesNoTrace:
    """Sending a log is how a run reports itself, not a step of its work — so it belongs in
    neither the live message nor the log file. One name list decides both."""

    @pytest.mark.asyncio
    async def test_a_successful_emit_records_nothing(self):
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = {}
            await ActionExecutor.execute(EMIT_LOG_ACTION_NAME, {"block": {}})

        assert drain_log_capture() == []

    @pytest.mark.asyncio
    async def test_a_failed_emit_records_nothing_either(self):
        """The failure path captures too, so it needs the same exemption — a log line that
        could not be delivered is not something the run did wrong."""
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.side_effect = RuntimeError("emit wire down")
            with pytest.raises(RuntimeError):
                await ActionExecutor.execute(EMIT_LOG_ACTION_NAME, {"block": {}})

        assert drain_log_capture() == []

    @pytest.mark.asyncio
    async def test_an_ordinary_action_is_still_recorded(self):
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = {"ok": True}
            await ActionExecutor.execute("do_thing", {"a": 1})

        assert [e["event"] for e in drain_log_capture()] == ["action"]


class TestWhatTheBlockShows:
    """The gateway wraps the answer in a transport envelope; its block shows the answer.

    Only the gateway route unwraps, and it does so in its own dispatch method — the other
    routes never call this, so there is no shape-sniffing to get wrong."""

    ENVELOPE: dict[str, Any] = {
        "id": "external-action-executor-0d95",
        "status": "COMPLETED",
        "result": {"datasets": []},
        "error": None,
    }

    def test_a_gateway_envelope_is_stripped_to_its_answer(self):
        assert ActionExecutor._unwrap_envelope(self.ENVELOPE) == {"datasets": []}

    def test_a_failed_gateway_call_shows_its_reason(self):
        """The gateway reports failure as a value rather than raising, so this is the success
        path — reading ``result`` alone would show None and lose the reason."""
        failed = {"id": "x", "status": "FAILED", "result": None, "error": "Action not found"}

        assert ActionExecutor._unwrap_envelope(failed) == "Action not found"

    def test_the_api_route_never_unwraps(self):
        """It already returns the action's own answer, so a value of its own that happens to
        look like an envelope is never at risk — that route does not call this at all."""
        source = inspect.getsource(ActionExecutor._execute_via_api)

        assert "_unwrap_envelope" not in source
        assert "_unwrap_envelope" in inspect.getsource(ActionExecutor._execute_via_gateway)

    def test_a_gateway_response_of_an_unexpected_shape_is_shown_whole(self):
        """The key check is a guard, so a malformed response is shown rather than reduced to
        nothing."""
        odd = {"status": "COMPLETED"}

        assert ActionExecutor._unwrap_envelope(odd) == odd

    @pytest.mark.parametrize("value", ["a string", None, 42])
    def test_a_non_dict_passes_through(self, value):
        assert ActionExecutor._unwrap_envelope(value) == value


class TestTheApiRouteNeedsARuntime:
    """An emit is its own API call: it reads credentials from the environment and needs a
    channel to appear in. Someone driving the SDK from their own program has neither, so the
    call goes unlogged rather than failing an emit for every action."""

    @pytest.mark.asyncio
    async def test_it_logs_when_the_runtime_gave_it_both(self):
        configure_auto_action_logs(True)
        seen: list[str] = []

        async def record(*, action_name, **kwargs):
            seen.append(action_name)
            return {"ok": True}

        with patch.object(ActionExecutor, "_execute_action", record):
            await ActionExecutor.execute("do_thing", {})

        assert seen == ["emit_log", "do_thing", "emit_log"]

    @pytest.mark.parametrize(
        "missing",
        [
            pytest.param(["ZAMP_CHANNEL_ID"], id="no channel"),
            pytest.param(["ZAMP_BASE_URL"], id="no base url"),
            pytest.param(["ZAMP_AUTH_TOKEN"], id="no auth token"),
        ],
    )
    @pytest.mark.asyncio
    async def test_it_stays_quiet_without_them(self, monkeypatch, missing):
        configure_auto_action_logs(True)
        for name in missing:
            monkeypatch.delenv(name, raising=False)
        seen: list[str] = []

        async def record(*, action_name, **kwargs):
            seen.append(action_name)
            return {"ok": True}

        with patch.object(ActionExecutor, "_execute_action", record):
            await ActionExecutor.execute("do_thing", {}, base_url="https://api.example", auth_token="tok")

        assert seen == ["do_thing"], "the action still runs; only its log is skipped"
