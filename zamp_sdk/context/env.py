"""Names of the environment variables the runtime injects into each sandboxed
execution. They identify the agent context that SDK output should attach to.

Defined in one place and shared across the SDK so the variable names stay
consistent across features.
"""

ENV_CHANNEL_TYPE = "ZAMP_CHANNEL_TYPE"
ENV_CHANNEL_ID = "ZAMP_CHANNEL_ID"
ENV_STREAMING_ID = "ZAMP_STREAMING_ID"
ENV_MESSAGE_ID = "ZAMP_MESSAGE_ID"
ENV_TOOL_CALL_ID = "ZAMP_TOOL_CALL_ID"
ENV_RUN_ID = "ZAMP_RUN_ID"
