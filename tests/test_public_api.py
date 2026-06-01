import zamp_sdk


class TestPublicApi:
    def test_action_executor_importable(self):
        from zamp_sdk import ActionExecutor

        assert hasattr(ActionExecutor, "execute")

    def test_retry_policy_importable(self):
        from zamp_sdk import RetryPolicy

        assert hasattr(RetryPolicy, "default")

    def test_sdk_config_importable(self):
        from zamp_sdk import SdkConfig

        assert hasattr(SdkConfig, "model_fields")

    def test_execution_mode_importable(self):
        from zamp_sdk import ExecutionMode

        assert ExecutionMode.SYNC.value == "SYNC"
        assert ExecutionMode.ASYNC.value == "ASYNC"
        assert ExecutionMode.INLINE.value == "INLINE"

    def test_emit_log_importable(self):
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

        assert callable(emit_log)
        assert callable(emit_text)
        assert callable(emit_tool_use)
        assert callable(emit_tool_result)
        assert hasattr(EmitLogResult, "model_fields")
        assert TextContentBlock(content="hi").type.value == "text"
        assert ToolUseContentBlock(name="x").type.value == "tool_use"
        assert ToolResultContentBlock(content="ok").type.value == "tool_result"

    def test_all_exports(self):
        expected = {
            "ActionExecutor",
            "BaseActivity",
            "BaseWorkflow",
            "CodeWorkflowCoreParams",
            "ContentBlock",
            "ContentBlockType",
            "EmitLogResult",
            "ExecutionMode",
            "InnerContentBlock",
            "RetryPolicy",
            "SdkConfig",
            "TextContentBlock",
            "ToolEmitLogBlock",
            "ToolResultContentBlock",
            "ToolUseContentBlock",
            "emit_log",
            "emit_text",
            "emit_tool_result",
            "emit_tool_use",
        }
        assert set(zamp_sdk.__all__) == expected
