# --- Inline execution: POST /actions with execution_mode=INLINE runs the action
# inside the request and answers with its terminal state, so there is no GET to
# poll. The platform bounds an inline run to INLINE_SERVER_MAX_SECONDS (pantheon's
# INLINE_MAX_SECONDS) and gives up first; the request timeout adds a margin on
# top of that bound so a run the server timed out comes back as a TIMED_OUT
# action rather than as a client-side timeout, whatever the caller asked for.
INLINE_SERVER_MAX_SECONDS = 25.0
INLINE_REQUEST_TIMEOUT_MARGIN_SECONDS = 5.0
