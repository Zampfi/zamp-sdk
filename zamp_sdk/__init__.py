from zamp_sdk import evals, mocks
from zamp_sdk.action_executor import ActionExecutor, ExecutionMode
from zamp_sdk.action_executor.models import RetryPolicy, SdkConfig
from zamp_sdk.context import (
    ChannelContext,
    ChannelType,
    ToolExecutionMode,
    bind_channel_context,
    clear_channel_context,
    current_channel_context,
)
from zamp_sdk.db.utils.errors import AgentDbError
from zamp_sdk.logging import (
    ContentBlock,
    ContentBlockType,
    EmitLogResult,
    LoggingConfig,
    LogLevel,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
    bind_logging_config,
    configure_auto_action_logs,
    configure_logging,
    drain_log_capture,
    emit_debug,
    emit_error,
    emit_info,
    emit_log,
    emit_text,
    emit_tool_result,
    emit_tool_use,
    start_log_capture,
)
from zamp_sdk.user_input import (
    AWAITING_USER_INPUT,
    InputOption,
    UserInputResponse,
    multiple_choice,
    parse_user_input,
    request_user_input,
    resume_script,
    run_workflow,
    select_one,
    text_input,
    user_input_from,
)
from zamp_sdk.version import __version__ as __version__
from zamp_sdk.workflows import (
    BaseActivity,
    BaseWorkflow,
)

_LAZY_DB = {"db", "datasets"}


def __getattr__(name: str):
    # zamp_sdk.db.datasets pulls in sqlalchemy; it is loaded on first use, not when zamp_sdk is imported.
    if name in _LAZY_DB:
        import importlib

        db = importlib.import_module("zamp_sdk.db")
        return db if name == "db" else getattr(db, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AWAITING_USER_INPUT",
    "ActionExecutor",
    "AgentDbError",
    "BaseActivity",
    "BaseWorkflow",
    "ChannelContext",
    "ChannelType",
    "ToolExecutionMode",
    "ContentBlock",
    "ContentBlockType",
    "EmitLogResult",
    "ExecutionMode",
    "LogLevel",
    "LoggingConfig",
    "UserInputResponse",
    "InputOption",
    "RetryPolicy",
    "SdkConfig",
    "bind_channel_context",
    "clear_channel_context",
    "bind_logging_config",
    "configure_auto_action_logs",
    "configure_logging",
    "current_channel_context",
    "datasets",
    "drain_log_capture",
    "evals",
    "mocks",
    "start_log_capture",
    "TextContentBlock",
    "ToolResultContentBlock",
    "ToolUseContentBlock",
    "emit_debug",
    "emit_error",
    "emit_info",
    "emit_log",
    "emit_text",
    "emit_tool_result",
    "emit_tool_use",
    "multiple_choice",
    "parse_user_input",
    "request_user_input",
    "resume_script",
    "run_workflow",
    "select_one",
    "text_input",
    "user_input_from",
]
