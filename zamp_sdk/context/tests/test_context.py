import uuid

import pytest
from pydantic import ValidationError

from zamp_sdk.context import (
    ChannelContext,
    ChannelType,
    bind_channel_context,
    clear_channel_context,
    resolve_channel_context,
    resolve_context,
)


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


class TestResolveContext:
    def test_reads_injected_env_vars(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-123")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "tc-9")
        monkeypatch.setenv("ZAMP_STREAMING_ID", "stream-1")
        monkeypatch.setenv("ZAMP_MESSAGE_ID", "msg-1")
        monkeypatch.setenv("ZAMP_RUN_ID", "run-1")

        ctx = resolve_context()

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
        assert resolve_context() == {}

    def test_partial_context(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-7")
        assert resolve_context() == {"channel_id": "conv-7"}


class TestChannelContextModel:
    def _kwargs(self, **overrides) -> dict:
        base = {
            "channel_type": "conversation",
            "channel_id": str(uuid.uuid4()),
            "streaming_id": "s",
            "message_id": "m",
            "tool_call_id": "t",
            "run_id": "r",
        }
        base.update(overrides)
        return base

    def test_valid_coerces_types(self):
        cid = uuid.uuid4()
        cc = ChannelContext(**self._kwargs(channel_type="conversation", channel_id=str(cid)))
        assert cc.channel_type is ChannelType.CONVERSATION
        assert cc.channel_id == cid  # str coerced to UUID

    def test_task_channel_type(self):
        cc = ChannelContext(**self._kwargs(channel_type="task"))
        assert cc.channel_type is ChannelType.TASK

    def test_channel_type_restricted_to_conversation_and_task(self):
        assert {ct.value for ct in ChannelType} == {"conversation", "task"}

    def test_invalid_channel_type_rejected(self):
        with pytest.raises(ValidationError):
            ChannelContext(**self._kwargs(channel_type="user"))

    def test_non_uuid_channel_id_rejected(self):
        with pytest.raises(ValidationError):
            ChannelContext(**self._kwargs(channel_id="not-a-uuid"))


class TestResolveChannelContext:
    """The channel context the SDK attaches once when calling the platform: a validated
    ``ChannelContext`` from the sandbox env, the bound context outside a sandbox, or None
    when no complete, valid one is available."""

    def _full_sandbox_env(self, monkeypatch, channel_id: str) -> None:
        monkeypatch.setenv("INSIDE_SANDBOX", "true")
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", channel_id)
        monkeypatch.setenv("ZAMP_STREAMING_ID", "s")
        monkeypatch.setenv("ZAMP_MESSAGE_ID", "m")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "t")
        monkeypatch.setenv("ZAMP_RUN_ID", "r")

    def test_resolves_full_sandbox_env(self, monkeypatch):
        cid = uuid.uuid4()
        self._full_sandbox_env(monkeypatch, str(cid))
        cc = resolve_channel_context()
        assert cc is not None
        assert cc.channel_id == cid
        assert cc.channel_type is ChannelType.CONVERSATION

    def test_none_when_channel_id_not_uuid(self, monkeypatch):
        self._full_sandbox_env(monkeypatch, "conv-1")
        assert resolve_channel_context() is None

    def test_none_when_partial(self, monkeypatch):
        # Missing streaming/message/tool/run -> incomplete -> not a valid ChannelContext.
        monkeypatch.setenv("INSIDE_SANDBOX", "true")
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", str(uuid.uuid4()))
        assert resolve_channel_context() is None

    def test_none_when_no_context(self):
        # Not a sandbox and nothing bound -> None.
        assert resolve_channel_context() is None

    def test_uses_bound_context_outside_sandbox(self):
        cid = uuid.uuid4()
        bind_channel_context(
            ChannelContext(
                channel_type="task",
                channel_id=str(cid),
                streaming_id="s",
                message_id="m",
                tool_call_id="t",
                run_id="r",
            )
        )
        try:
            cc = resolve_channel_context()
            assert cc is not None
            assert cc.channel_type is ChannelType.TASK
            assert cc.channel_id == cid
        finally:
            clear_channel_context()
