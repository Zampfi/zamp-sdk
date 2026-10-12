import inspect
from collections.abc import Callable

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from zamp_sdk.evals.constants import UNTRACED_ARGUMENT_NAME_SUFFIXES, UNTRACED_ARGUMENT_NAMES


def bind_arguments(
    func: Callable[..., object], args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, object]:
    bound = inspect.signature(func).bind(*args, **kwargs)
    bound.apply_defaults()

    arguments = dict(bound.arguments)
    for parameter in bound.signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            extra_arguments = arguments.pop(parameter.name)
            arguments.update({name: value for name, value in extra_arguments.items() if name not in arguments})

    return arguments


def key_from_arguments(arguments: dict[str, object], key_argument: str | None) -> str | None:
    return None if key_argument is None else str(arguments[key_argument])


def arguments_to_trace(arguments: dict[str, object]) -> dict[str, JsonValue]:
    return {name: to_json_value(value) for name, value in arguments.items() if not _is_untraced(name)}


def to_json_value(value: object) -> JsonValue:
    return to_jsonable_python(value, fallback=repr, bytes_mode="base64")


def _is_untraced(name: str) -> bool:
    lowered = name.lower()

    return lowered in UNTRACED_ARGUMENT_NAMES or lowered.endswith(UNTRACED_ARGUMENT_NAME_SUFFIXES)
