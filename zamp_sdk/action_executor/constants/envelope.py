"""The shape the gateway route wraps an action's answer in."""

# ``{"id": ..., "status": "COMPLETED", "result": <the action's own output>, "error": None}``.
# The gateway returns this whole object to authored code — deployed workflows read ``status``
# and ``result`` off it themselves, so it cannot be unwrapped on the way out. The API route
# unwraps its equivalent before returning, which is why only one route has to be handled.
#
# All three keys must be present before a value is treated as an envelope, so an action whose
# own output happens to carry a ``result`` key is left alone.
ACTION_ENVELOPE_KEYS = frozenset({"id", "status", "result"})
