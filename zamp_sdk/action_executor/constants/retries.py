# Client-side retry defaults for transient 5xx on the action-create POST.
# Backoff mirrors the polling cadence (see polling.py). Kept in float seconds
# (not timedelta) because they drive client-side asyncio.sleep directly.
DEFAULT_5XX_MAX_ATTEMPTS = 10
DEFAULT_5XX_INITIAL_INTERVAL_SECONDS = 1.0
DEFAULT_5XX_MAX_INTERVAL_SECONDS = 30.0
DEFAULT_5XX_BACKOFF_COEFFICIENT = 2.0
