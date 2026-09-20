"""What ``ActionExecutor.execute`` records and shows for each call it runs.

Three things meet at this seam: the step buffer that becomes the run's log file, the spawned
task ids a caller needs to list, and the live log blocks. They are tested together because the
bug worth catching is one of them changing the others.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import configure_auto_action_logs
from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.capture import drain_log_capture, start_log_capture
from zamp_sdk.logging.constants import EMIT_LOG_ACTION_NAME
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
        with patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run:
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
            patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run,
            patch("zamp_sdk.logging.auto.emit_tool_use", new_callable=AsyncMock) as use,
            patch("zamp_sdk.logging.auto.emit_tool_result", new_callable=AsyncMock) as result,
        ):
            run.return_value = {"ok": True}
            use.return_value = "emit_1"
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

        with patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run:
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
            patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run,
            patch(
                "zamp_sdk.logging.auto.emit_tool_use",
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
        with patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run:
            run.return_value = {}
            await ActionExecutor.execute(EMIT_LOG_ACTION_NAME, {"block": {}})

        assert drain_log_capture() == []

    @pytest.mark.asyncio
    async def test_a_failed_emit_records_nothing_either(self):
        """The failure path captures too, so it needs the same exemption — a log line that
        could not be delivered is not something the run did wrong."""
        start_log_capture()
        with patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run:
            run.side_effect = RuntimeError("emit wire down")
            with pytest.raises(RuntimeError):
                await ActionExecutor.execute(EMIT_LOG_ACTION_NAME, {"block": {}})

        assert drain_log_capture() == []

    @pytest.mark.asyncio
    async def test_an_ordinary_action_is_still_recorded(self):
        start_log_capture()
        with patch.object(ActionExecutor, "_dispatch", new_callable=AsyncMock) as run:
            run.return_value = {"ok": True}
            await ActionExecutor.execute("do_thing", {"a": 1})

        assert [e["event"] for e in drain_log_capture()] == ["action"]
