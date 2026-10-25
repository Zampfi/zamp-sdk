"""The cap on what is sent to the platform, and the rule that any refusal stops sending."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import TextContentBlock, emit_log, emit_text
from zamp_sdk.action_executor import ExecutionMode
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost
from zamp_sdk.logging import bind_emit_budget, emit_budget, emit_sending_stopped
from zamp_sdk.logging.auto import _should_log
from zamp_sdk.logging.constants import (
    DEFAULT_MAX_EMITS,
    EMIT_SENDING_STOPPED_ERROR,
    EMIT_TIMEOUT,
    LogLevel,
)
from zamp_sdk.logging.log_control import configure_auto_action_logs, configure_logging

EXECUTE = "zamp_sdk.action_executor.ActionExecutor.execute"


def _block() -> TextContentBlock:
    return TextContentBlock(content="hi")


@pytest.fixture
def execute():
    mock = AsyncMock(return_value={"success": True})
    with patch(EXECUTE, mock):
        yield mock


class TestBudget:
    def test_spends_up_to_the_limit_then_refuses(self):
        bind_emit_budget(2)
        assert [emit_budget.try_spend_emit() for _ in range(4)] == [True, True, False, False]
        assert emit_sending_stopped()

    def test_warns_exactly_once(self):
        bind_emit_budget(1)
        with patch.object(emit_budget.logger, "warning") as warning:
            emit_budget.try_spend_emit()
            for _ in range(3):
                emit_budget.try_spend_emit()
            emit_budget.stop_emit_sending()
        warning.assert_called_once()
        assert warning.call_args.kwargs == {"limit": 1, "sent": 1}

    def test_stopped_sticks_before_the_limit(self):
        bind_emit_budget(10)
        emit_budget.stop_emit_sending()
        assert emit_budget.try_spend_emit() is False

    def test_rebinding_resets(self):
        bind_emit_budget(1)
        emit_budget.try_spend_emit()
        emit_budget.try_spend_emit()
        bind_emit_budget(1)
        assert not emit_sending_stopped()
        assert emit_budget.try_spend_emit() is True

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_a_non_positive_limit(self, bad):
        with pytest.raises(ValueError):
            bind_emit_budget(bad)

    def test_the_default_limit_matches_the_platform_cap(self):
        assert emit_budget._PROCESS_BUDGET.limit == DEFAULT_MAX_EMITS == 1200

    @pytest.mark.asyncio
    async def test_parent_sees_what_gathered_children_spent(self):
        bind_emit_budget(10)

        async def child():
            emit_budget.try_spend_emit()

        await asyncio.gather(child(), child(), child())
        assert emit_budget._budget.get().sent == 3


class TestHosts:
    @pytest.mark.asyncio
    async def test_unbound_api_host_shares_the_process_budget(self, execute):
        emit_budget._PROCESS_BUDGET.limit = 5
        await asyncio.gather(*(emit_log(_block()) for _ in range(10)))
        assert execute.await_count == 5

    @pytest.mark.asyncio
    async def test_unbound_actions_hub_is_uncapped(self, execute, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTION_HOST, ExecutionHost.ACTIONS_HUB.value)
        emit_budget._PROCESS_BUDGET.limit = 1
        emit_budget.stop_emit_sending()
        assert not emit_sending_stopped()
        await asyncio.gather(*(emit_log(_block()) for _ in range(3)))
        assert execute.await_count == 3


class TestEmitLog:
    @pytest.mark.asyncio
    async def test_sends_inline_with_the_emit_timeout(self, execute):
        await emit_log(_block())
        assert execute.call_args.kwargs["execution_mode"] is ExecutionMode.INLINE
        assert execute.call_args.kwargs["action_start_to_close_timeout"] == EMIT_TIMEOUT == timedelta(seconds=15)

    @pytest.mark.asyncio
    async def test_past_the_cap_it_does_not_send_but_still_logs_locally(self, execute):
        bind_emit_budget(1)
        await emit_log(_block())
        with patch("zamp_sdk.logging.logging.logger.info") as info:
            result = await emit_text("local line")
        assert (result.ok, result.sending_stopped, result.error) == (False, True, EMIT_SENDING_STOPPED_ERROR)
        assert execute.await_count == 1
        info.assert_called_once_with("emit_text", content="local line")

    @pytest.mark.asyncio
    async def test_auto_emits_are_capped_too(self, execute):
        bind_emit_budget(1)
        await emit_log(_block())
        assert (await emit_log(_block(), auto=True)).sending_stopped is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "refusal",
        [
            {"success": False, "budget_exhausted": True},
            {"id": "a", "status": "FAILED", "result": {"success": False}, "error": None},
            {"id": "a", "status": "FAILED", "result": None, "error": "nope"},
            None,
        ],
    )
    async def test_a_refusal_stops_sending(self, refusal):
        execute = AsyncMock(return_value=refusal)
        with patch(EXECUTE, execute):
            await emit_log(_block())
            second = await emit_log(_block())
        assert execute.await_count == 1
        assert second.sending_stopped is True

    @pytest.mark.asyncio
    async def test_a_raise_stops_sending(self):
        execute = AsyncMock(side_effect=RuntimeError("422"))
        with patch(EXECUTE, execute):
            first = await emit_log(_block())
            await emit_log(_block())
        assert first.ok is False and first.sending_stopped is False
        assert execute.await_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ok_result",
        [
            {"success": True},
            {"id": "a", "status": "COMPLETED", "result": {"success": True}, "error": None},
        ],
    )
    async def test_success_keeps_sending(self, ok_result):
        execute = AsyncMock(return_value=ok_result)
        with patch(EXECUTE, execute):
            await emit_log(_block())
            await emit_log(_block())
        assert execute.await_count == 2

    @pytest.mark.asyncio
    async def test_level_filtered_lines_do_not_spend(self, execute):
        bind_emit_budget(1)
        configure_logging(level="error")
        await emit_log(_block(), level=LogLevel.DEBUG)
        assert emit_budget._budget.get().sent == 0


class TestAutoGate:
    def test_should_log_is_false_once_sending_stopped(self):
        configure_auto_action_logs(True)
        assert _should_log("do_thing", None) is True
        emit_budget.stop_emit_sending()
        assert _should_log("do_thing", None) is False
        assert _should_log("do_thing", True) is False
