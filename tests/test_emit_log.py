import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from zamp_sdk import (
    EmitLogResult,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
    emit_log,
    emit_text,
    emit_tool_result,
    emit_tool_use,
)
from zamp_sdk.emit_log import (
    EMIT_ID_PREFIX,
    _new_emit_id,
    _resolve_context,
    _stringify_tool_result,
)


@pytest.fixture(autouse=True)
def _clear_zamp_env(monkeypatch):
    """Every test starts with a clean slate — context-resolving env vars off."""
    for var in (
        "ZAMP_CHANNEL_TYPE",
        "ZAMP_CHANNEL_ID",
        "ZAMP_STREAMING_ID",
        "ZAMP_MESSAGE_ID",
        "ZAMP_TOOL_CALL_ID",
        "ZAMP_RUN_ID",
    ):
        monkeypatch.delenv(var, raising=False)


class TestResolveContext:
    def test_reads_injected_env_vars(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-123")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "tc-9")
        monkeypatch.setenv("ZAMP_STREAMING_ID", "stream-1")
        monkeypatch.setenv("ZAMP_MESSAGE_ID", "msg-1")
        monkeypatch.setenv("ZAMP_RUN_ID", "run-1")

        ctx = _resolve_context()

        assert ctx == {
            "channel_type": "task",
            "channel_id": "task-123",
            "streaming_id": "stream-1",
            "message_id": "msg-1",
            "tool_call_id": "tc-9",
            "run_id": "run-1",
        }

    def test_drops_unset_keys(self):
        # autouse fixture cleared everything
        assert _resolve_context() == {}

    def test_partial_context(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-7")
        ctx = _resolve_context()
        assert ctx == {"channel_id": "conv-7"}


class TestNewEmitId:
    def test_has_expected_prefix(self):
        new_id = _new_emit_id()
        assert new_id.startswith(EMIT_ID_PREFIX)
        # uuid4().hex is 32 chars
        assert len(new_id) == len(EMIT_ID_PREFIX) + 32

    def test_ids_are_unique(self):
        ids = {_new_emit_id() for _ in range(50)}
        assert len(ids) == 50


class TestStringifyToolResult:
    def test_none_becomes_success_marker(self):
        assert _stringify_tool_result(None) == "Success (no output)"

    def test_string_passthrough(self):
        assert _stringify_tool_result("already a string") == "already a string"

    def test_dict_pretty_printed(self):
        out = _stringify_tool_result({"a": 1, "b": "two"})
        assert json.loads(out) == {"a": 1, "b": "two"}
        # indent=2 ⇒ multi-line
        assert "\n" in out

    def test_list_pretty_printed(self):
        out = _stringify_tool_result([1, 2, 3])
        assert json.loads(out) == [1, 2, 3]
        assert "\n" in out

    def test_basemodel_pretty_printed(self):
        class _M(BaseModel):
            name: str
            count: int

        out = _stringify_tool_result(_M(name="x", count=2))
        assert json.loads(out) == {"name": "x", "count": 2}

    def test_other_falls_back_to_str(self):
        assert _stringify_tool_result(42) == "42"


class TestEmitLogText:
    @pytest.mark.asyncio
    async def test_text_block_calls_action_executor(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-1")

        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="• **Progress** — building..."))

        assert isinstance(result, EmitLogResult)
        assert result.ok is True
        assert result.result == {"success": True}
        execute.assert_awaited_once()
        action_name, params = execute.call_args.args
        assert action_name == "emit_log"
        assert params["block"]["type"] == "text"
        assert params["block"]["content"] == "• **Progress** — building..."
        assert params["context"]["channel_id"] == "conv-1"
        assert params["context"]["channel_type"] == "conversation"
        # summary kwarg is forwarded so server-side logs read nicely
        assert execute.call_args.kwargs.get("summary")

    @pytest.mark.asyncio
    async def test_auto_stamps_parent_block_id_from_env(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        execute = AsyncMock(return_value=None)
        block = TextContentBlock(content="hello")

        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_log(block)

        # Auto-stamped on the block itself...
        assert block.parent_block_id == "toolu_abc"
        # ...and present in the serialized payload.
        assert execute.call_args.args[1]["block"]["parent_block_id"] == "toolu_abc"

    @pytest.mark.asyncio
    async def test_explicit_parent_block_id_not_overwritten(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        execute = AsyncMock(return_value=None)
        block = TextContentBlock(content="hi", parent_block_id="caller_supplied")

        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_log(block)

        assert block.parent_block_id == "caller_supplied"
        assert execute.call_args.args[1]["block"]["parent_block_id"] == "caller_supplied"


class TestEmitLogErrors:
    @pytest.mark.asyncio
    async def test_error_never_raises(self):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="hello"))

        assert result.ok is False
        assert "boom" in (result.error or "")
        assert result.result is None


class TestEmitText:
    @pytest.mark.asyncio
    async def test_wraps_string_as_text_block(self):
        execute = AsyncMock(return_value={"ok": 1})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_text("step done")

        assert result.ok is True
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "text"
        assert block["content"] == "step done"


class TestEmitToolUse:
    @pytest.mark.asyncio
    async def test_returns_minted_id_with_prefix(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            returned = await emit_tool_use(
                "GMAIL_SEND",
                display_title="Sending daily report",
                input={"to": "a@b.com"},
            )

        assert returned.startswith(EMIT_ID_PREFIX)
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_use"
        assert block["id"] == returned
        assert block["name"] == "GMAIL_SEND"
        assert block["display_title"] == "Sending daily report"
        assert json.loads(block["input_json"]) == {"to": "a@b.com"}

    @pytest.mark.asyncio
    async def test_respects_caller_supplied_id(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            returned = await emit_tool_use("X", id="my-custom-id")

        assert returned == "my-custom-id"
        assert execute.call_args.args[1]["block"]["id"] == "my-custom-id"

    @pytest.mark.asyncio
    async def test_no_input_means_no_input_json(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_tool_use("X")

        assert execute.call_args.args[1]["block"]["input_json"] is None

    @pytest.mark.asyncio
    async def test_id_returned_even_when_emit_fails(self):
        execute = AsyncMock(side_effect=RuntimeError("network down"))
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            # Caller must still be able to pair the eventual tool_result, so
            # the helper swallows the failure and returns the id anyway.
            returned = await emit_tool_use("X")

        assert returned.startswith(EMIT_ID_PREFIX)


class TestEmitToolResult:
    @pytest.mark.asyncio
    async def test_pairs_id_and_stringifies_dict(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_tool_result("emit_xyz", {"sent": True, "count": 3}, name="GMAIL_SEND")

        assert result.ok is True
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_result"
        assert block["id"] == "emit_xyz"
        assert block["name"] == "GMAIL_SEND"
        assert json.loads(block["content"]) == {"sent": True, "count": 3}

    @pytest.mark.asyncio
    async def test_none_content_becomes_success_marker(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_tool_result("emit_xyz", None)

        assert execute.call_args.args[1]["block"]["content"] == "Success (no output)"

    @pytest.mark.asyncio
    async def test_string_content_passes_through(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_tool_result("emit_xyz", "raw text payload")

        assert execute.call_args.args[1]["block"]["content"] == "raw text payload"


class TestEmitToolUseResultPairing:
    @pytest.mark.asyncio
    async def test_full_pair_share_id(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            tool_id = await emit_tool_use("GMAIL_SEND", input={"to": "a@b.com"})
            res = await emit_tool_result(tool_id, "sent", name="GMAIL_SEND")

        assert res.ok is True
        use_block = execute.call_args_list[0].args[1]["block"]
        result_block = execute.call_args_list[1].args[1]["block"]
        assert use_block["type"] == "tool_use"
        assert result_block["type"] == "tool_result"
        assert use_block["id"] == result_block["id"] == tool_id


class TestBlockShapes:
    """Quick guard against silent schema drift from pantheon mirror."""

    def test_text_block_type_value(self):
        assert TextContentBlock(content="hi").type.value == "text"

    def test_tool_use_block_type_value(self):
        assert ToolUseContentBlock(name="X").type.value == "tool_use"

    def test_tool_result_block_type_value(self):
        assert ToolResultContentBlock(content="r").type.value == "tool_result"
