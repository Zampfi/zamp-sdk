POLL_INITIAL_INTERVAL_SECONDS = 1.0
POLL_MAX_INTERVAL_SECONDS = 30.0
# Default client poll ceiling (1 hour). Callers extend it for longer actions by
# passing action_start_to_close_timeout; the poll never gives up below this.
POLL_TIMEOUT_SECONDS = 3600.0
