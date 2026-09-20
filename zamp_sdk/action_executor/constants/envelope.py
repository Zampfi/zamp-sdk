"""The shape the gateway route wraps an action's answer in."""

# ``{"id", "status", "result", "error"}``. All three keys must be present before a value is
# treated as an envelope, so an action whose own output has a ``result`` key is left alone.
ACTION_ENVELOPE_KEYS = frozenset({"id", "status", "result"})
