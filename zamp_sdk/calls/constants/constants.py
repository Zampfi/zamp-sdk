UNSENT_ARGUMENT_NAMES = frozenset(
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
UNSENT_ARGUMENT_NAME_SUFFIXES = (
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
    "_authorization",
)

PLACEHOLDER_CIRCULAR_VALUE = "<{type} that contains itself>"
