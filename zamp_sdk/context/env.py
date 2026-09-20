"""Names of the environment variables the SDK reads from its runtime.

Most identify the agent context that SDK output should attach to, injected per
sandboxed execution. ``ENV_EXECUTION_HOST`` is different in kind: it is set once by a
host process to declare what runtime the SDK is in, and therefore how actions dispatch.

There is deliberately no "am I in a sandbox" variable. Nothing needs to ask: the SDK
picks a context source by precedence and a transport from ``ENV_EXECUTION_HOST``.

Defined in one place and shared across the SDK so the variable names stay
consistent across features.
"""

ENV_CHANNEL_TYPE = "ZAMP_CHANNEL_TYPE"
ENV_CHANNEL_ID = "ZAMP_CHANNEL_ID"
ENV_STREAMING_ID = "ZAMP_STREAMING_ID"
ENV_MESSAGE_ID = "ZAMP_MESSAGE_ID"
ENV_TOOL_CALL_ID = "ZAMP_TOOL_CALL_ID"
ENV_RUN_ID = "ZAMP_RUN_ID"
ENV_EXECUTION_HOST = "ZAMP_SDK_EXECUTION_HOST"

# This run's LoggingConfig, a field per variable in the same style as the channel context above.
# They carry the platform's logging decision to a process that has no workflow input to put it
# on; a code-executor run is handed the same model on its input instead.
#
# Unlike the channel variables, these are read independently rather than all-or-none: a partial
# channel context is no context at all, whereas a logging config missing a field simply keeps
# that field's default.
ENV_LOG_LEVEL = "ZAMP_LOG_LEVEL"
ENV_LOG_ENABLED = "ZAMP_LOG_ENABLED"
ENV_AUTO_ACTION_LOGS = "ZAMP_AUTO_ACTION_LOGS"
