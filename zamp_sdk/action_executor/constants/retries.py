# 5xx retry policy for the action transport calls (POST /actions and the
# GET /actions/{id} poll). A transient server error should be retried rather
# than surfaced as a spurious action failure. The backoff mirrors the polling
# backoff (see polling.py) so the retry cadence is consistent across both.

# Total POST attempts on 5xx (1 initial + 9 retries).
RETRY_5XX_MAX_ATTEMPTS = 10
RETRY_5XX_INITIAL_INTERVAL_SECONDS = 1.0
RETRY_5XX_MAX_INTERVAL_SECONDS = 30.0
RETRY_5XX_BACKOFF_COEFFICIENT = 2.0
