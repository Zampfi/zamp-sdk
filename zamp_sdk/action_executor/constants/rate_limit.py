"""The platform's rate-limit refusal contract, as the SDK reads it."""

# The status of a refusal over HTTP. Nothing was started.
HTTP_TOO_MANY_REQUESTS = 429

# Sent with a 429: the seconds until the refused call can succeed.
RETRY_AFTER_HEADER = "Retry-After"
