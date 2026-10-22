# --- Inline: a single POST /actions that waits for the action's result. The wait
# outlasts the platform's own inline timeout by a grace, so the platform's answer
# (including TIMED_OUT) always arrives before the client gives up.
# Mirrors the platform's inline default; change both together.
INLINE_SERVER_DEFAULT_TIMEOUT_SECONDS = 60.0
INLINE_RESPONSE_GRACE_SECONDS = 10.0
