from enum import Enum

# A trace never holds the instance or a credential: these names exactly, or a name holding any of the parts.
UNTRACED_ARGUMENT_NAMES = frozenset({"self", "cls", "headers", "auth"})
UNTRACED_ARGUMENT_NAME_PARTS = ("authorization", "credential", "key", "password", "secret", "token")

# A faked httpx.Response has no real request, but raise_for_status() needs one, so it gets this stand-in.
PLACEHOLDER_REQUEST_METHOD = "GET"
PLACEHOLDER_REQUEST_URL = "https://fixture.invalid"


class DecoratedCallKind(str, Enum):
    EXTERNAL = "external"
    OBSERVE = "observe"


class FixtureErrorCode(str, Enum):
    FIXTURE_MISSING = "FIXTURE_MISSING"
    FIXTURE_EXHAUSTED = "FIXTURE_EXHAUSTED"
