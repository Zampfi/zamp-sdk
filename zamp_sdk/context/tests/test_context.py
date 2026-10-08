import sys
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError

from zamp_sdk.context import (
    ChannelContext,
    ChannelType,
    ToolExecutionMode,
    bind_channel_context,
    clear_channel_context,
    current_branch_context,
    current_eval_execution_id,
    resolve_channel_context,
    resolve_context,
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
        "ZAMP_BRANCH_ID",
        "ZAMP_DB_BRANCH_MODE",
        "ZAMP_ENVIRONMENT",
        "ZAMP_TOOL_EXECUTION_MODE",
        "ZAMP_EVAL_EXECUTION_ID",
        "ZAMP_SDK_EXECUTION_HOST",
    ):
        monkeypatch.delenv(var, raising=False)


class TestCurrentBranchContext:
    def test_reads_injected_branch(self, monkeypatch):
        monkeypatch.setenv("ZAMP_BRANCH_ID", "feature-x")
        monkeypatch.setenv("ZAMP_DB_BRANCH_MODE", "test")
        assert current_branch_context() == {"branch_id": "feature-x", "db_branch_mode": "test"}

    def test_empty_outside_a_branch(self):
        assert current_branch_context() == {}

    def test_includes_environment_in_a_branch(self, monkeypatch):
        monkeypatch.setenv("ZAMP_BRANCH_ID", "feature-x")
        monkeypatch.setenv("ZAMP_ENVIRONMENT", "test")
        assert current_branch_context() == {"branch_id": "feature-x", "environment": "test"}

    def test_mode_and_environment_ignored_without_a_branch(self, monkeypatch):
        monkeypatch.setenv("ZAMP_DB_BRANCH_MODE", "test")
        monkeypatch.setenv("ZAMP_ENVIRONMENT", "test")
        assert current_branch_context() == {}

    def test_drops_blank_values(self, monkeypatch):
        monkeypatch.setenv("ZAMP_BRANCH_ID", "feature-x")
        monkeypatch.setenv("ZAMP_DB_BRANCH_MODE", "")
        assert current_branch_context() == {"branch_id": "feature-x"}


class TestCurrentEvalExecutionId:
    def test_none_outside_an_eval_run(self):
        assert current_eval_execution_id() is None

    def test_reads_the_injected_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_EVAL_EXECUTION_ID", "run1-1-item1-1")
        assert current_eval_execution_id() == "run1-1-item1-1"

    def test_blank_is_none(self, monkeypatch):
        monkeypatch.setenv("ZAMP_EVAL_EXECUTION_ID", "")
        assert current_eval_execution_id() is None

    def test_actions_hub_reads_the_bound_metadata_context(self, monkeypatch):
        monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")
        monkeypatch.setenv("ZAMP_EVAL_EXECUTION_ID", "from-env")

        with _bound_metadata_context({"eval_execution_id": "run1-1-item1-1"}):
            assert current_eval_execution_id() == "run1-1-item1-1"

    def test_actions_hub_none_when_the_context_has_no_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")

        with _bound_metadata_context({"branch_id": "b1"}):
            assert current_eval_execution_id() is None

    def test_actions_hub_none_when_no_context_is_bound(self, monkeypatch):
        monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")

        with _bound_metadata_context(None):
            assert current_eval_execution_id() is None


class _ZampMetadataContext(BaseModel):
    branch_id: str | None = None
    eval_execution_id: str | None = None


def _bound_metadata_context(metadata):
    bound = {"zamp_metadata_context": metadata}
    return patch.dict(
        sys.modules,
        {
            "zamp_public_workflow_sdk.actions_hub.models.common_models": SimpleNamespace(
                ZampMetadataContext=_ZampMetadataContext
            ),
            "zamp_public_workflow_sdk.actions_hub.utils.context_utils": SimpleNamespace(
                get_variable_from_context=bound.get
            ),
        },
    )


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

    def test_reads_tool_execution_mode_when_set(self, monkeypatch):
        monkeypatch.setenv("ZAMP_TOOL_EXECUTION_MODE", "async")
        assert resolve_context() == {"tool_execution_mode": "async"}


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

    def test_tool_execution_mode_defaults_to_sync(self):
        """A context without the field — every foreground one, and any sent by an older
        platform — is a sync tool call."""
        assert ChannelContext(**self._kwargs()).tool_execution_mode is ToolExecutionMode.SYNC

    def test_async_tool_execution_mode(self):
        cc = ChannelContext(**self._kwargs(tool_execution_mode="async"))
        assert cc.tool_execution_mode is ToolExecutionMode.ASYNC

    def test_invalid_tool_execution_mode_rejected(self):
        with pytest.raises(ValidationError):
            ChannelContext(**self._kwargs(tool_execution_mode="later"))

    def test_tool_execution_mode_survives_a_round_trip(self):
        cc = ChannelContext(**self._kwargs(tool_execution_mode="async"))
        restored = ChannelContext.model_validate_json(cc.model_dump_json())
        assert restored.tool_execution_mode is ToolExecutionMode.ASYNC

    def test_tool_execution_mode_values(self):
        assert {mode.value for mode in ToolExecutionMode} == {"sync", "async"}


class TestResolveChannelContext:
    """The channel context the SDK attaches once when calling the platform: a validated
    ``ChannelContext`` from the sandbox env, the bound context outside a sandbox, or None
    when no complete, valid one is available."""

    def _full_sandbox_env(self, monkeypatch, channel_id: str) -> None:
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

    def test_sandbox_env_without_mode_is_sync(self, monkeypatch):
        self._full_sandbox_env(monkeypatch, str(uuid.uuid4()))
        cc = resolve_channel_context()
        assert cc is not None
        assert cc.tool_execution_mode is ToolExecutionMode.SYNC

    def test_sandbox_env_reads_async_mode(self, monkeypatch):
        self._full_sandbox_env(monkeypatch, str(uuid.uuid4()))
        monkeypatch.setenv("ZAMP_TOOL_EXECUTION_MODE", "async")
        cc = resolve_channel_context()
        assert cc is not None
        assert cc.tool_execution_mode is ToolExecutionMode.ASYNC

    def test_none_when_channel_id_not_uuid(self, monkeypatch):
        self._full_sandbox_env(monkeypatch, "conv-1")
        assert resolve_channel_context() is None

    def test_none_when_partial(self, monkeypatch):
        # Missing streaming/message/tool/run -> incomplete -> not a valid ChannelContext.
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", str(uuid.uuid4()))
        assert resolve_channel_context() is None

    def test_none_when_no_context(self):
        # Not a sandbox and nothing bound -> None.
        assert resolve_channel_context() is None

    def test_none_when_resolution_raises_unexpectedly(self, monkeypatch):
        # Resolution is best-effort: a failure that isn't a ValidationError must still
        # resolve to None rather than breaking the action call it decorates.
        def _boom() -> dict:
            raise RuntimeError("boom")

        monkeypatch.setattr("zamp_sdk.context.resolve.resolve_context", _boom)
        assert resolve_channel_context() is None

    def test_uses_bound_context_on_an_actions_hub_host(self, monkeypatch):
        """The bound context is the source only for an ACTIONS_HUB host — a workflow bound
        it in-process. An API host reads the environment instead, which is what stops
        sandboxed code from binding its own and redirecting its output."""
        monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")
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

    def test_an_api_host_ignores_a_bound_context(self):
        """Sandboxed code can import bind_channel_context and call it. On the API path the
        bound value must never be consulted, or that code could redirect its own output."""
        bind_channel_context(
            ChannelContext(
                channel_type="task",
                channel_id=str(uuid.uuid4()),
                streaming_id="s",
                message_id="m",
                tool_call_id="t",
                run_id="r",
            )
        )
        try:
            assert resolve_channel_context() is None
        finally:
            clear_channel_context()
