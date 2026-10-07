"""The platform's rate-limit refusal contract, as the SDK reads it."""

# The status of a refusal over HTTP. Nothing was started.
HTTP_TOO_MANY_REQUESTS = 429

# A refusal that arrives in-band - inside a successful response, as an action's error string -
# starts with this prefix. The prefix is the contract; the wording after it is not.
RATE_LIMITED_PREFIX = "RATE_LIMITED:"
