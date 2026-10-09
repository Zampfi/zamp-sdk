from enum import Enum

CALL_NAME_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
KEY_VALUE_PATTERN = r"^[^#\s]+$"
ERROR_TYPE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$"

UNTRACED_ARGUMENT_NAMES = frozenset({"self", "cls", "headers", "auth", "token", "credentials"})

FIXTURE_REQUEST_METHOD = "GET"
FIXTURE_REQUEST_URL = "https://{name}.invalid"


class DecoratedCallKind(str, Enum):
    EXTERNAL = "external"
    OBSERVE = "observe"


class FixtureErrorCode(str, Enum):
    FIXTURE_MISSING = "FIXTURE_MISSING"
    FIXTURE_EXHAUSTED = "FIXTURE_EXHAUSTED"
