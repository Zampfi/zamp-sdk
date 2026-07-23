import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from zamp_sdk import (
    EmitLogResult,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
    drain_log_capture,
    emit_log,
    emit_text,
    emit_tool_result,
    emit_tool_use,
    start_log_capture,
)
from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.capture import capture_active, capture_step, suppress_step_capture
from zamp_sdk.logging.constants import EMIT_ID_PREFIX
from zamp_sdk.logging.utils import new_emit_id, stringify_tool_result
from zamp_sdk.version import __version__


@pytest.fixture(autouse=True)
def _clear_zamp_env(monkeypatch):
    """Every test starts with a clean slate — context-resolving env vars off."""
    for var in (
        "INSIDE_SANDBOX",
        "ZAMP_CHANNEL_TYPE",
        "ZAMP_CHANNEL_ID",
        "ZAMP_STREAMING_ID",
        "ZAMP_MESSAGE_ID",
        "ZAMP_TOOL_CALL_ID",
        "ZAMP_RUN_ID",
    ):
        monkeypatch.delenv(var, raising=False)


class TestNewEmitId:
    def test_has_expected_prefix(self):
        new_id = new_emit_id()
        assert new_id.startswith(EMIT_ID_PREFIX)
        # uuid4().hex is 32 chars
        assert len(new_id) == len(EMIT_ID_PREFIX) + 32

    def test_ids_are_unique(self):
        ids = {new_emit_id() for _ in range(50)}
        assert len(ids) == 50


class TestStringifyToolResult:
    def test_none_becomes_success_marker(self):
        assert stringify_tool_result(None) == "Success (no output)"

    def test_string_passthrough(self):
        assert stringify_tool_result("already a string") == "already a string"

    def test_dict_pretty_printed(self):
        out = stringify_tool_result({"a": 1, "b": "two"})
        assert json.loads(out) == {"a": 1, "b": "two"}
        # indent=2 ⇒ multi-line
        assert "\n" in out

    def test_list_pretty_printed(self):
        out = stringify_tool_result([1, 2, 3])
        assert json.loads(out) == [1, 2, 3]
        assert "\n" in out

    def test_basemodel_pretty_printed(self):
        class _M(BaseModel):
            name: str
            count: int

        out = stringify_tool_result(_M(name="x", count=2))
        assert json.loads(out) == {"name": "x", "count": 2}

    def test_other_falls_back_to_str(self):
        assert stringify_tool_result(42) == "42"


class TestEmitLogText:
    @pytest.mark.asyncio
    async def test_text_block_calls_action_executor(self):
        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="• **Progress** — building..."))

        assert isinstance(result, EmitLogResult)
        assert result.ok is True
        assert result.result == {"success": True}
        execute.assert_awaited_once()
        action_name, params = execute.call_args.args
        assert action_name == "emit_log"
        assert params["block"]["type"] == "text"
        assert params["block"]["content"] == "• **Progress** — building..."
        # emit_log sends only the block; routing rides on the injected channel_context
        assert "context" not in params
        # summary kwarg is forwarded so server-side logs read nicely
        assert execute.call_args.kwargs.get("summary")

    @pytest.mark.asyncio
    async def test_auto_stamps_parent_block_id_from_env(self, monkeypatch):
        monkeypatch.setenv("INSIDE_SANDBOX", "true")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "toolu_abc")
        execute = AsyncMock(return_value=None)
        block = TextContentBlock(content="hello")

        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
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

        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            await emit_log(block)

        assert block.parent_block_id == "caller_supplied"
        assert execute.call_args.args[1]["block"]["parent_block_id"] == "caller_supplied"


class TestEmitLogErrors:
    @pytest.mark.asyncio
    async def test_error_never_raises(self):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            result = await emit_log(TextContentBlock(content="hello"))

        assert result.ok is False
        assert "boom" in (result.error or "")
        assert result.result is None


class TestEmitText:
    @pytest.mark.asyncio
    async def test_wraps_string_as_text_block(self):
        execute = AsyncMock(return_value={"ok": 1})
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            result = await emit_text("step done")

        assert result.ok is True
        block = execute.call_args.args[1]["block"]
        assert block["type"] == "text"
        assert block["content"] == "step done"


class TestEmitToolUse:
    @pytest.mark.asyncio
    async def test_returns_minted_id_with_prefix(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
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
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            returned = await emit_tool_use("X", id="my-custom-id")

        assert returned == "my-custom-id"
        assert execute.call_args.args[1]["block"]["id"] == "my-custom-id"

    @pytest.mark.asyncio
    async def test_no_input_means_no_input_json(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            await emit_tool_use("X")

        assert execute.call_args.args[1]["block"]["input_json"] is None

    @pytest.mark.asyncio
    async def test_id_returned_even_when_emit_fails(self):
        execute = AsyncMock(side_effect=RuntimeError("network down"))
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            # Caller must still be able to pair the eventual tool_result, so
            # the helper swallows the failure and returns the id anyway.
            returned = await emit_tool_use("X")

        assert returned.startswith(EMIT_ID_PREFIX)


class TestEmitToolResult:
    @pytest.mark.asyncio
    async def test_pairs_id_and_stringifies_dict(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
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
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            await emit_tool_result("emit_xyz", None)

        assert execute.call_args.args[1]["block"]["content"] == "Success (no output)"

    @pytest.mark.asyncio
    async def test_string_content_passes_through(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            await emit_tool_result("emit_xyz", "raw text payload")

        assert execute.call_args.args[1]["block"]["content"] == "raw text payload"


class TestEmitToolUseResultPairing:
    @pytest.mark.asyncio
    async def test_full_pair_share_id(self):
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            tool_id = await emit_tool_use("GMAIL_SEND", input={"to": "a@b.com"})
            res = await emit_tool_result(tool_id, "sent", name="GMAIL_SEND")

        assert res.ok is True
        use_block = execute.call_args_list[0].args[1]["block"]
        result_block = execute.call_args_list[1].args[1]["block"]
        assert use_block["type"] == "tool_use"
        assert result_block["type"] == "tool_result"
        assert use_block["id"] == result_block["id"] == tool_id


class TestBlockShapes:
    """Quick guard against silent schema drift in the content-block definitions."""

    def test_text_block_type_value(self):
        assert TextContentBlock(content="hi").type.value == "text"

    def test_tool_use_block_type_value(self):
        assert ToolUseContentBlock(name="X").type.value == "tool_use"

    def test_tool_result_block_type_value(self):
        assert ToolResultContentBlock(content="r").type.value == "tool_result"


class TestLogCapture:
    """The capture buffer records clean, logger-style steps: emitted blocks (compact,
    not full serialized blocks) and every ActionExecutor call (name + input + output),
    so a runtime can return every step the script ran."""

    @pytest.fixture(autouse=True)
    def _reset_buffer(self):
        from zamp_sdk.capture.step_capture import _log_buffer

        _log_buffer.set(None)
        yield
        _log_buffer.set(None)

    @pytest.mark.asyncio
    async def test_captures_clean_block_entries(self, monkeypatch):
        monkeypatch.setenv("INSIDE_SANDBOX", "true")
        start_log_capture()
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
            await emit_text("hello")
            tid = await emit_tool_use("MyTool", display_title="Doing", input={"x": 1})
            await emit_tool_result(tid, {"ok": True}, name="MyTool")

        steps = drain_log_capture()
        # Every entry carries the SDK version (like the logger).
        assert all(s["sdk_version"] == __version__ for s in steps)
        assert steps[0] == {
            "sdk_version": __version__,
            "event": "emit_text",
            "content": "hello",
        }
        assert steps[1] == {
            "sdk_version": __version__,
            "event": "emit_tool_use",
            "id": tid,
            "name": "MyTool",
            "display_title": "Doing",
            "input_json": json.dumps({"x": 1}),
        }
        assert steps[2]["event"] == "emit_tool_result"
        assert steps[2]["id"] == tid
        # Compact — not the full serialized block.
        assert "parent_block_id" not in steps[0]
        assert "type" not in steps[0]

    def test_captures_action_call(self):
        start_log_capture()
        ActionExecutor._capture_action_step("do_thing", {"a": 1}, {"ok": True})
        assert drain_log_capture() == [
            {
                "sdk_version": __version__,
                "event": "action",
                "name": "do_thing",
                "input": {"a": 1},
                "output": {"ok": True},
            }
        ]

    @pytest.mark.asyncio
    async def test_emit_log_suppresses_its_own_action_capture(self, monkeypatch):
        # emit_log captures its block; the emit_log action call must NOT also be captured.
        monkeypatch.setenv("INSIDE_SANDBOX", "true")
        start_log_capture()

        async def fake_execute(name, params, **kwargs):
            # Simulate what ActionExecutor.execute does after dispatch.
            ActionExecutor._capture_action_step(name, params, None)
            return None

        with patch("zamp_sdk.logging.logging.ActionExecutor.execute", fake_execute):
            await emit_text("hi")

        # Only the block; the action was suppressed inside emit_log.
        assert [s["event"] for s in drain_log_capture()] == ["emit_text"]

    def test_suppress_step_capture(self):
        start_log_capture()
        capture_step({"event": "a"})
        with suppress_step_capture():
            capture_step({"event": "b"})  # suppressed
        capture_step({"event": "c"})
        assert [s["event"] for s in drain_log_capture()] == ["a", "c"]

    def test_capture_is_noop_without_start(self):
        # No start_log_capture() -> capture is a no-op (blocks still stream live elsewhere).
        ActionExecutor._capture_action_step("do_thing", {"a": 1}, {"ok": True})
        assert drain_log_capture() == []

    def test_capture_active_reflects_state(self):
        # Guard used to skip building entries when they would be discarded (e.g. sandbox).
        assert capture_active() is False  # nothing started
        start_log_capture()
        assert capture_active() is True
        with suppress_step_capture():
            assert capture_active() is False  # suppressed
        assert capture_active() is True
