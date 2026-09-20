"""Where an action call is dispatched, and which of those places log it."""

from enum import StrEnum


class Route(StrEnum):
    """The three ways ``ActionExecutor.execute`` can dispatch a call.

    ``API`` — no local orchestrator: POSTed to the Zamp API and polled.
    ``GATEWAY`` — an ActionsHub is present but does not register this action, so it is routed
    out to the platform.
    ``LOCAL_AH`` — an ActionsHub is present and owns the action, so it runs in-process.
    """

    API = "api"
    GATEWAY = "gateway"
    LOCAL_AH = "local_ah"


# Routes whose calls the SDK logs to the live message on the script's behalf. ``LOCAL_AH`` is
# absent on purpose: an action registered on the worker that runs it is an in-process call —
# plumbing, not a tool call the user is waiting on.
LOGGED_ROUTES = frozenset({Route.API, Route.GATEWAY})
