from enum import StrEnum

CALL_NAME_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
KEY_VALUE_PATTERN = r"^[^#\s]+$"
ERROR_TYPE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$"

UNTRACED_ARGUMENT_NAMES = frozenset({"self", "cls", "headers", "auth", "token", "credentials"})

FIXTURE_REQUEST_METHOD = "GET"
FIXTURE_REQUEST_URL = "https://{name}.invalid"


class DoorKind(StrEnum):
    EXTERNAL = "external"
    OBSERVE = "observe"
    READ_TRACE = "read_trace"
