from enum import Enum

# A trace never holds the instance or a credential: an argument whose lowercased name is one of these names,
# or ends in one of the suffixes, is left out. Whole names only, so max_tokens or sort_key stay in.
UNTRACED_ARGUMENT_NAMES = frozenset(
    {
        "self",
        "cls",
        "headers",
        "auth",
        "authorization",
        "token",
        "credentials",
        "password",
        "secret",
        "api_key",
        "apikey",
        "client_secret",
        "access_token",
        "refresh_token",
    }
)
UNTRACED_ARGUMENT_NAME_SUFFIXES = ("_password", "_secret", "_token", "_api_key", "_credentials")

# Name of the action a decorated external call goes through in an eval trial, to be answered from its fixture.
EVAL_EXTERNAL_CALL_ACTION_NAME = "eval_external_call"

# Name of the action an observed step goes through in an eval trial, to record its outcome in the trace.
EVAL_OBSERVED_STEP_ACTION_NAME = "eval_observed_step"

# Name of the action read_trace goes through in an eval trial.
EVAL_READ_TRACE_ACTION_NAME = "eval_read_trace"

# A faked httpx.Response has no real request, but raise_for_status() needs one, so it gets this stand-in.
PLACEHOLDER_REQUEST_METHOD = "GET"
PLACEHOLDER_REQUEST_URL = "https://fixture.invalid"


class DecoratedCallKind(str, Enum):
    EXTERNAL_CALL = "external"
    OBSERVE = "observe"


class FixtureErrorCode(str, Enum):
    FIXTURE_MISSING = "FIXTURE_MISSING"
    FIXTURE_EXHAUSTED = "FIXTURE_EXHAUSTED"
