import inspect
from collections.abc import Callable

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from zamp_sdk.evals.constants import UNTRACED_ARGUMENT_NAMES


def bind_arguments(
    func: Callable[..., object], args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, object]:
    bound = inspect.signature(func).bind(*args, **kwargs)
    bound.apply_defaults()

    arguments = dict(bound.arguments)
    for parameter in bound.signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            del arguments[parameter.name]
            arguments.update(bound.arguments[parameter.name])

    return arguments


def key_value(arguments: dict[str, object], key: str | None) -> str | None:
    return None if key is None else str(arguments[key])


def trace_arguments(arguments: dict[str, object]) -> dict[str, JsonValue]:
    return {name: to_json_value(value) for name, value in arguments.items() if name not in UNTRACED_ARGUMENT_NAMES}


def to_json_value(value: object) -> JsonValue:
    return to_jsonable_python(value, fallback=repr, bytes_mode="base64")
