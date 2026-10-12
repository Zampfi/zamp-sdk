"""The shape the gateway route wraps an action's answer in."""

# ``{"id", "status", "result", "error"}``. All three keys must be present before a value is
# treated as an action response, so an action whose own output has a ``result`` key is left alone.
ACTION_RESPONSE_KEYS = frozenset({"id", "status", "result"})
