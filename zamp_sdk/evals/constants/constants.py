from enum import StrEnum

EVAL_DOOR_ACTION = "eval_door"

CALL_NAME_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
KEY_VALUE_PATTERN = r"^[^#\s]+$"
ERROR_TYPE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$"

SECRET_ARGUMENT_NAMES = frozenset({"headers", "auth", "token", "credentials"})

FIXTURE_REQUEST_METHOD = "GET"
FIXTURE_REQUEST_URL = "https://{name}.invalid"


class DoorKind(StrEnum):
    EXTERNAL = "external"
    OBSERVE = "observe"
    READ_TRACE = "read_trace"
