from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk.emit_log import (
    EmitLogResult,
    MarkdownLog,
    ToolCallLog,
    _resolve_context,
    emit_log,
)


class TestResolveContext:
    def test_reads_injected_env_vars(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-123")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "tc-9")
        ctx = _resolve_context()
        assert ctx["channel_type"] == "task"
        assert ctx["channel_id"] == "task-123"
        assert ctx["tool_call_id"] == "tc-9"

    def test_drops_unset_keys(self, monkeypatch):
        for var in (
            "ZAMP_CHANNEL_TYPE",
            "ZAMP_CHANNEL_ID",
            "ZAMP_STREAMING_ID",
            "ZAMP_MESSAGE_ID",
            "ZAMP_TOOL_CALL_ID",
            "ZAMP_RUN_ID",
        ):
            monkeypatch.delenv(var, raising=False)
        assert _resolve_context() == {}


class TestEmitLogMarkdown:
    @pytest.mark.asyncio
    async def test_markdown_block_calls_action_executor(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-1")

        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                MarkdownLog(content="building...", level="info", title="step 1")
            )

        assert isinstance(result, EmitLogResult)
        assert result.ok is True
        assert result.result == {"success": True}
        execute.assert_awaited_once()
        args, _ = execute.call_args
        assert args[0] == "emit_log"
        params = args[1]
        block = params["block"]
        assert block["type"] == "markdown"
        assert block["content"] == "building..."
        assert block["level"] == "info"
        assert block["title"] == "step 1"
        assert params["target"] == "current"
        assert params["context"]["channel_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_new_task_target_passes_task_title(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                MarkdownLog(content="logs"),
                target="new_task",
                task_title="Build logs",
            )

        assert result.ok is True
        params = execute.call_args.args[1]
        assert params["target"] == "new_task"
        assert params["task_title"] == "Build logs"


class TestEmitLogToolCall:
    @pytest.mark.asyncio
    async def test_tool_call_block_serializes_fields(self):
        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                ToolCallLog(
                    tool_name="GMAIL_SEND",
                    tool_input={"to": "a@b.com"},
                    tool_output="sent",
                    is_error=False,
                )
            )

        assert result.ok is True
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_call"
        assert block["tool_name"] == "GMAIL_SEND"
        assert block["tool_input"] == {"to": "a@b.com"}
        assert block["tool_output"] == "sent"
        assert block["is_error"] is False


class TestEmitLogErrors:
    @pytest.mark.asyncio
    async def test_error_never_raises(self):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(MarkdownLog(content="hello"))

        assert result.ok is False
        assert "boom" in (result.error or "")
