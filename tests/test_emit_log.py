import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    EmitLogResult,
    MarkdownContentBlock,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
    emit_log,
)
from zamp_sdk.emit_log import _resolve_context


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


class TestEmitLogText:
    @pytest.mark.asyncio
    async def test_text_block_calls_action_executor(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-1")

        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                [TextContentBlock(content="• **Progress** — building...")]
            )

        assert isinstance(result, EmitLogResult)
        assert result.ok is True
        assert result.result == {"success": True}
        execute.assert_awaited_once()
        args, _ = execute.call_args
        assert args[0] == "emit_log"
        params = args[1]
        assert len(params["blocks"]) == 1
        b = params["blocks"][0]
        assert b["type"] == "text"
        assert b["content"] == "• **Progress** — building..."
        assert params["target"] == "current"
        assert params["context"]["channel_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_markdown_block_serializes_with_type_markdown(self):
        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                [MarkdownContentBlock(content="# Progress\n\nDone **42** records.")]
            )

        assert result.ok is True
        b = execute.call_args.args[1]["blocks"][0]
        assert b["type"] == "markdown"
        assert b["content"] == "# Progress\n\nDone **42** records."

    @pytest.mark.asyncio
    async def test_new_task_target_passes_task_title(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                [TextContentBlock(content="logs")],
                target="new_task",
                task_title="Build logs",
            )

        assert result.ok is True
        params = execute.call_args.args[1]
        assert params["target"] == "new_task"
        assert params["task_title"] == "Build logs"


class TestEmitLogToolCallPair:
    @pytest.mark.asyncio
    async def test_paired_tool_use_and_result_serialize(self):
        execute = AsyncMock(return_value={"success": True})
        tcid = str(uuid.uuid4())
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(
                [
                    ToolUseContentBlock(
                        id=tcid,
                        name="GMAIL_SEND",
                        display_title="Sending daily report email",
                        input_json=json.dumps({"to": "a@b.com"}),
                    ),
                    ToolResultContentBlock(
                        id=tcid,
                        name="GMAIL_SEND",
                        content="sent",
                    ),
                ]
            )

        assert result.ok is True
        params = execute.call_args.args[1]
        assert len(params["blocks"]) == 2
        use, res = params["blocks"]
        assert use["type"] == "tool_use"
        assert use["id"] == tcid
        assert use["display_title"] == "Sending daily report email"
        assert use["input_json"] == json.dumps({"to": "a@b.com"})
        assert res["type"] == "tool_result"
        assert res["id"] == tcid  # paired
        assert res["content"] == "sent"


class TestEmitLogErrors:
    @pytest.mark.asyncio
    async def test_empty_blocks_returns_ok_false(self):
        result = await emit_log([])
        assert result.ok is False
        assert "empty" in (result.error or "")

    @pytest.mark.asyncio
    async def test_error_never_raises(self):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log([TextContentBlock(content="hello")])

        assert result.ok is False
        assert "boom" in (result.error or "")
