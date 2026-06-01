import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from zamp_sdk import (
    EmitLogResult,
    TextContentBlock,
    ToolEmitLogBlock,
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


class TestEmitLogWrapping:
    """emit_log wraps every inner block in a ToolEmitLogBlock tagged with the
    running tool's id, so the platform groups it under the right parent."""

    @pytest.mark.asyncio
    async def test_wraps_text_block_with_tool_id_from_env(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-1")

        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="• Progress..."))

        assert isinstance(result, EmitLogResult)
        assert result.ok is True
        execute.assert_awaited_once()
        action_name, params = execute.call_args.args
        assert action_name == "emit_log"

        block = params["block"]
        # The serialized payload is a wrapper, NOT a raw text block.
        assert block["type"] == "tool_emit_log"
        assert block["tool_id"] == "toolu_abc"
        # Inner content carries the actual emit_log payload.
        assert block["content"]["type"] == "text"
        assert block["content"]["content"] == "• Progress..."

        # Context still flows through alongside.
        assert params["context"]["channel_id"] == "conv-1"
        assert execute.call_args.kwargs.get("summary")

    @pytest.mark.asyncio
    async def test_wraps_tool_use_block(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)

        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_log(
                ToolUseContentBlock(
                    id="emit_tc1",
                    name="GMAIL_SEND",
                    display_title="Sending mail",
                    input_json='{"to":"a@b.com"}',
                )
            )

        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_emit_log"
        assert block["tool_id"] == "toolu_parent"
        inner = block["content"]
        assert inner["type"] == "tool_use"
        assert inner["id"] == "emit_tc1"
        assert inner["name"] == "GMAIL_SEND"
        assert inner["display_title"] == "Sending mail"

    @pytest.mark.asyncio
    async def test_wraps_tool_result_block(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)

        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_log(
                ToolResultContentBlock(id="emit_tc1", content="done")
            )

        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_emit_log"
        assert block["tool_id"] == "toolu_parent"
        assert block["content"]["type"] == "tool_result"
        assert block["content"]["content"] == "done"

    @pytest.mark.asyncio
    async def test_skipped_when_tool_call_id_unset(self):
        """Without ZAMP_TOOL_CALL_ID we can't route the log to a parent —
        the SDK refuses to emit and returns ok=False rather than guessing."""
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="hi"))

        assert result.ok is False
        assert "ZAMP_TOOL_CALL_ID" in (result.error or "")
        execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_inner_block_has_no_parent_block_id_field(self, monkeypatch):
        """parent_block_id is gone from the inner block model — the relationship
        lives only on the wrapper. Catches accidental re-introduction."""
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        block = TextContentBlock(content="hello")
        # Field doesn't exist on the model at all
        assert "parent_block_id" not in block.model_dump()


class TestEmitLogErrors:
    @pytest.mark.asyncio
    async def test_error_never_raises(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="hello"))

        assert result.ok is False
        assert "boom" in (result.error or "")
        assert result.result is None


class TestEmitText:
    @pytest.mark.asyncio
    async def test_wraps_string_as_text_block(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        execute = AsyncMock(return_value={"ok": 1})
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_text("step done")

        assert result.ok is True
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_emit_log"
        assert block["tool_id"] == "toolu_abc"
        assert block["content"]["type"] == "text"
        assert block["content"]["content"] == "step done"


class TestEmitToolUse:
    @pytest.mark.asyncio
    async def test_returns_minted_id_with_prefix(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            returned = await emit_tool_use(
                "GMAIL_SEND",
                display_title="Sending daily report",
                input={"to": "a@b.com"},
            )

        assert returned.startswith(EMIT_ID_PREFIX)
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_emit_log"
        assert block["tool_id"] == "toolu_parent"
        inner = block["content"]
        assert inner["type"] == "tool_use"
        assert inner["id"] == returned
        assert inner["name"] == "GMAIL_SEND"
        assert inner["display_title"] == "Sending daily report"
        assert json.loads(inner["input_json"]) == {"to": "a@b.com"}

    @pytest.mark.asyncio
    async def test_respects_caller_supplied_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            returned = await emit_tool_use("X", id="my-custom-id")

        assert returned == "my-custom-id"
        assert execute.call_args.args[1]["block"]["content"]["id"] == "my-custom-id"

    @pytest.mark.asyncio
    async def test_no_input_means_no_input_json(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_tool_use("X")

        assert execute.call_args.args[1]["block"]["content"]["input_json"] is None

    @pytest.mark.asyncio
    async def test_id_returned_even_when_emit_fails(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(side_effect=RuntimeError("network down"))
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            # Caller must still be able to pair the eventual tool_result, so
            # the helper swallows the failure and returns the id anyway.
            returned = await emit_tool_use("X")

        assert returned.startswith(EMIT_ID_PREFIX)


class TestEmitToolResult:
    @pytest.mark.asyncio
    async def test_pairs_id_and_stringifies_dict(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            result = await emit_tool_result("emit_xyz", {"sent": True, "count": 3}, name="GMAIL_SEND")

        assert result.ok is True
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "tool_emit_log"
        assert block["tool_id"] == "toolu_parent"
        inner = block["content"]
        assert inner["type"] == "tool_result"
        assert inner["id"] == "emit_xyz"
        assert inner["name"] == "GMAIL_SEND"
        assert json.loads(inner["content"]) == {"sent": True, "count": 3}

    @pytest.mark.asyncio
    async def test_none_content_becomes_success_marker(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_tool_result("emit_xyz", None)

        assert execute.call_args.args[1]["block"]["content"]["content"] == "Success (no output)"

    @pytest.mark.asyncio
    async def test_string_content_passes_through(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            await emit_tool_result("emit_xyz", "raw text payload")

        assert execute.call_args.args[1]["block"]["content"]["content"] == "raw text payload"


class TestEmitToolUseResultPairing:
    @pytest.mark.asyncio
    async def test_full_pair_share_id_and_tool_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_parent")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.emit_log.ActionExecutor.execute", execute):
            tool_id = await emit_tool_use("GMAIL_SEND", input={"to": "a@b.com"})
            res = await emit_tool_result(tool_id, "sent", name="GMAIL_SEND")

        assert res.ok is True
        use_wrapper = execute.call_args_list[0].args[1]["block"]
        result_wrapper = execute.call_args_list[1].args[1]["block"]

        # Both share the same outer tool_id (the parent sandbox_user_exec)…
        assert use_wrapper["tool_id"] == result_wrapper["tool_id"] == "toolu_parent"
        # …and the inner blocks pair via their own shared id.
        assert use_wrapper["content"]["type"] == "tool_use"
        assert result_wrapper["content"]["type"] == "tool_result"
        assert use_wrapper["content"]["id"] == result_wrapper["content"]["id"] == tool_id


class TestBlockShapes:
    """Quick guard against silent schema drift from pantheon mirror."""

    def test_text_block_type_value(self):
        assert TextContentBlock(content="hi").type.value == "text"

    def test_tool_use_block_type_value(self):
        assert ToolUseContentBlock(name="X").type.value == "tool_use"

    def test_tool_result_block_type_value(self):
        assert ToolResultContentBlock(content="r").type.value == "tool_result"

    def test_tool_emit_log_block_wraps_inner(self):
        wrapper = ToolEmitLogBlock(
            tool_id="toolu_X",
            content=TextContentBlock(content="hi"),
        )
        assert wrapper.type.value == "tool_emit_log"
        assert wrapper.tool_id == "toolu_X"
        assert wrapper.content.type.value == "text"

    def test_tool_emit_log_block_accepts_tool_use_inner(self):
        wrapper = ToolEmitLogBlock(
            tool_id="toolu_X",
            content=ToolUseContentBlock(id="emit_1", name="X"),
        )
        assert wrapper.content.type.value == "tool_use"

    def test_tool_emit_log_block_accepts_tool_result_inner(self):
        wrapper = ToolEmitLogBlock(
            tool_id="toolu_X",
            content=ToolResultContentBlock(id="emit_1", content="r"),
        )
        assert wrapper.content.type.value == "tool_result"

    def test_tool_emit_log_block_rejects_nested_wrapper(self):
        """Wrapper can only hold inner block types — no wrapper-of-wrapper."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolEmitLogBlock(
                tool_id="toolu_X",
                content=ToolEmitLogBlock(
                    tool_id="toolu_Y",
                    content=TextContentBlock(content="nope"),
                ),
            )
