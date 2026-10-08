import inspect
from collections.abc import Callable

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from zamp_sdk.evals.constants import KEY_NOT_A_PARAMETER_ERROR, SECRET_ARGUMENT_NAMES


def raise_if_key_not_a_parameter(name: str, key: str | None, func: Callable[..., object]) -> None:
    if key is not None and key not in inspect.signature(func).parameters:
        raise ValueError(KEY_NOT_A_PARAMETER_ERROR.format(name=name, key=key, function=func.__qualname__))


def bind_arguments(
    func: Callable[..., object], args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, object]:
    bound = inspect.signature(func).bind(*args, **kwargs)
    bound.apply_defaults()

    return dict(bound.arguments)


def key_value(arguments: dict[str, object], key: str | None) -> str | None:
    if key is None or arguments[key] is None:
        return None

    return str(arguments[key])


def trace_arguments(arguments: dict[str, object]) -> dict[str, JsonValue]:
    return {name: to_json_value(value) for name, value in arguments.items() if name not in SECRET_ARGUMENT_NAMES}


def to_json_value(value: object) -> JsonValue:
    return to_jsonable_python(value, fallback=repr)
