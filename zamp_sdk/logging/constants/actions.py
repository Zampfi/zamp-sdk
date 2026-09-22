# Name of the action dispatched through ActionExecutor for every emitted block.
EMIT_LOG_ACTION_NAME = "emit_log"

# Prefix applied to identifiers generated for tool-call blocks emitted from a script.
EMIT_ID_PREFIX = "emit_"

# Actions the SDK records nothing about — neither a block in the live message nor an entry in
# the step buffer. Sending a log IS calling one, so they are how a run reports itself rather
# than steps of its work; logging emit_log would also call emit_log, forever. This set is the
# only thing preventing that, so an action added to the emit path has to be added here too —
# and it is the thing to grep for when wondering why one action leaves no trace.
NON_LOGGABLE_ACTIONS = frozenset({EMIT_LOG_ACTION_NAME})
