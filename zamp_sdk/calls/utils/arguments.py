import inspect

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from zamp_sdk.calls.constants import PLACEHOLDER_CIRCULAR_VALUE, UNSENT_ARGUMENT_NAME_SUFFIXES, UNSENT_ARGUMENT_NAMES


def bind_arguments(
    signature: inspect.Signature, args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, object]:
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()

    arguments = dict(bound.arguments)
    for parameter in bound.signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            extra_arguments = arguments.pop(parameter.name)
            arguments.update({name: value for name, value in extra_arguments.items() if name not in arguments})

    return arguments


def arguments_without_credentials(arguments: dict[str, object]) -> dict[str, JsonValue]:
    return {
        name: _without_credentials(to_json_value(value)) for name, value in arguments.items() if not _is_unsent(name)
    }


def to_json_value(value: object) -> JsonValue:
    try:
        return to_jsonable_python(value, fallback=repr, bytes_mode="base64")
    except ValueError:
        # A value that contains itself ("Circular reference detected")
        return PLACEHOLDER_CIRCULAR_VALUE.format(type=type(value).__name__)


def _without_credentials(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {name: _without_credentials(item) for name, item in value.items() if not _is_unsent(name)}
    if isinstance(value, list):
        return [_without_credentials(item) for item in value]

    return value


def _is_unsent(name: str) -> bool:
    normalised = name.lower().replace("-", "_").replace(" ", "_")

    return normalised in UNSENT_ARGUMENT_NAMES or normalised.endswith(UNSENT_ARGUMENT_NAME_SUFFIXES)
