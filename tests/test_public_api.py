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

    def test_logging_controls_importable(self):
        """Every name here has to be in ``__all__``: the code executor builds its sandbox
        facade from it, so a public helper missing from the list does not exist to authored
        code however well it is documented."""
        from zamp_sdk import (
            LogLevel,
            configure_auto_action_logs,
            configure_logging,
            emit_debug,
            emit_error,
            emit_info,
        )

        # A level is the word for it, so a skill writes "debug" rather than looking up 10.
        assert [str(level) for level in LogLevel] == ["debug", "info", "error"]
        # Ordering is severity, never the strings: alphabetically error would sort below info.
        assert LogLevel.DEBUG.severity < LogLevel.INFO.severity < LogLevel.ERROR.severity
        assert all(
            callable(fn)
            for fn in (
                emit_info,
                emit_debug,
                emit_error,
                configure_logging,
                configure_auto_action_logs,
            )
        )

    def test_all_exports(self):
        expected = {
            "ActionExecutor",
            "BaseActivity",
            "BaseWorkflow",
            "ContentBlock",
            "ContentBlockType",
            "EmitLogResult",
            "ExecutionMode",
            "RetryPolicy",
            "SdkConfig",
            "TextContentBlock",
            "ToolResultContentBlock",
            "ToolUseContentBlock",
            "emit_log",
            "emit_text",
            "emit_tool_result",
            "emit_tool_use",
            "AWAITING_USER_INPUT",
            "UserInputResponse",
            "InputOption",
            "multiple_choice",
            "parse_user_input",
            "request_user_input",
            "resume_script",
            "run_workflow",
            "select_one",
            "text_input",
            "user_input_from",
            "ChannelContext",
            "ChannelType",
            "bind_channel_context",
            "clear_channel_context",
            "current_channel_context",
            "start_log_capture",
            "drain_log_capture",
            # Agent-managed database access for scripts.
            "AgentDbError",
            "datasets",
            # Levelled logging + the two independent gates.
            "LogLevel",
            "LoggingConfig",
            "bind_logging_config",
            "emit_info",
            "emit_debug",
            "emit_error",
            "configure_logging",
            "configure_auto_action_logs",
        }
        assert set(zamp_sdk.__all__) == expected
