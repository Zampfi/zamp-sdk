from enum import Enum

# A trace never holds the instance or a credential: these names exactly, or a name holding any of the parts.
UNTRACED_ARGUMENT_NAMES = frozenset({"self", "cls", "headers", "auth"})
UNTRACED_ARGUMENT_NAME_PARTS = ("authorization", "credential", "key", "password", "secret", "token")

FIXTURE_REQUEST_METHOD = "GET"
FIXTURE_REQUEST_URL = "https://{name}.invalid"


class DecoratedCallKind(str, Enum):
    EXTERNAL = "external"
    OBSERVE = "observe"


class FixtureErrorCode(str, Enum):
    FIXTURE_MISSING = "FIXTURE_MISSING"
    FIXTURE_EXHAUSTED = "FIXTURE_EXHAUSTED"
