from enum import Enum

# An argument, or a key inside a dict argument at any depth, whose lowercased name is one of these names or ends in
# one of the suffixes is left out of the trace. Whole names only, so max_tokens or sort_key stay in.
UNTRACED_ARGUMENT_NAMES = frozenset(
    {
        "self",
        "cls",
        "headers",
        "auth",
        "authorization",
        "token",
        "jwt",
        "credentials",
        "password",
        "passwd",
        "pwd",
        "passphrase",
        "secret",
        "secret_key",
        "private_key",
        "access_key",
        "api_key",
        "apikey",
        "cookie",
        "cookies",
    }
)
UNTRACED_ARGUMENT_NAME_SUFFIXES = (
    "_password",
    "_passphrase",
    "_secret",
    "_secret_key",
    "_private_key",
    "_access_key",
    "_token",
    "_api_key",
    "_credentials",
    "_cookie",
)

# A faked httpx.Response has no real request, but raise_for_status() needs one, so it gets this stand-in.
PLACEHOLDER_REQUEST_METHOD = "GET"
PLACEHOLDER_REQUEST_URL = "https://fixture.invalid"


class DecoratedCallKind(str, Enum):
    EXTERNAL_CALL = "external_call"
    OBSERVED_STEP = "observed_step"


class FixtureErrorCode(str, Enum):
    FIXTURE_MISSING = "FIXTURE_MISSING"
    FIXTURE_EXHAUSTED = "FIXTURE_EXHAUSTED"
