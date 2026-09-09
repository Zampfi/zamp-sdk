# Agent-managed DB actions typically complete server-side in ~300ms, and the poll
# loop sleeps this interval BEFORE its first GET — so a 1.0s initial forced a
# ~700ms dead wait on every fast action. Start low so a fast action is caught in
# a few hundred ms instead of a full second.
POLL_INITIAL_INTERVAL_SECONDS = 0.1
POLL_MAX_INTERVAL_SECONDS = 30.0
# Multiplier applied to the poll interval after each attempt (exponential backoff).
# Gentle (1.5) so a mid-range action isn't overshot far past its completion to the
# next coarse poll point, while long actions still back off toward the 30s ceiling.
POLL_BACKOFF_COEFFICIENT = 1.5
# Default client poll ceiling (1 hour). Callers extend it for longer actions by
# passing action_start_to_close_timeout; the poll never gives up below this.
POLL_TIMEOUT_SECONDS = 3600.0
