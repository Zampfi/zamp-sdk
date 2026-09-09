# --- Result polling: GET /actions/{id} until the action reaches a terminal state.
# The action is running and healthy — we are only waiting for it to finish — so
# poll aggressively early. Agent-managed DB actions complete server-side in
# ~300ms, and the loop sleeps this interval BEFORE its first GET, so a 1.0s
# initial forced a ~700ms dead wait on every fast action.
POLL_INITIAL_INTERVAL_SECONDS = 0.1
POLL_BACKOFF_COEFFICIENT = 1.5
POLL_MAX_INTERVAL_SECONDS = 30.0
# Default poll ceiling (1 hour). Callers extend it for longer actions by passing
# action_start_to_close_timeout; the poll never gives up below this.
POLL_TIMEOUT_SECONDS = 3600.0

# --- Create-retry: POST /actions retried on a transient 5xx. Here the create
# endpoint is already FAILING, so back off gently — accelerating retries into a
# struggling server risks a retry-storm. Kept conservative and deliberately
# independent of the result-poll tuning above (tuning one must not move the other).
POST_RETRY_INITIAL_INTERVAL_SECONDS = 1.0
POST_RETRY_BACKOFF_COEFFICIENT = 2.0
POST_RETRY_MAX_INTERVAL_SECONDS = 30.0
POST_RETRY_TIMEOUT_SECONDS = 3600.0
