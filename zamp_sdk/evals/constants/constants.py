from enum import Enum

UNTRACED_ARGUMENT_NAMES = frozenset({"self", "cls", "headers", "auth", "token", "credentials"})

FIXTURE_REQUEST_METHOD = "GET"
FIXTURE_REQUEST_URL = "https://{name}.invalid"


class DecoratedCallKind(str, Enum):
    EXTERNAL = "external"
    OBSERVE = "observe"


class FixtureErrorCode(str, Enum):
    FIXTURE_MISSING = "FIXTURE_MISSING"
    FIXTURE_EXHAUSTED = "FIXTURE_EXHAUSTED"
