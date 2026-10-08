import inspect
from collections.abc import Callable

from pydantic import JsonValue, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from zamp_sdk.evals.constants import (
    INVALID_CALL_NAME_ERROR,
    INVALID_KEY_VALUE_ERROR,
    KEY_NOT_A_PARAMETER_ERROR,
    UNTRACED_ARGUMENT_NAMES,
)
from zamp_sdk.evals.models import CallName, KeyValue

_call_name = TypeAdapter(CallName)
_key_value = TypeAdapter(KeyValue)


def raise_if_invalid_decoration(name: str, key: str | None, func: Callable[..., object]) -> None:
    try:
        _call_name.validate_python(name)
    except ValidationError:
        raise ValueError(INVALID_CALL_NAME_ERROR.format(name=name)) from None

    if key is not None and key not in inspect.signature(func).parameters:
        raise ValueError(KEY_NOT_A_PARAMETER_ERROR.format(name=name, key=key, function=func.__qualname__))


def bind_arguments(
    func: Callable[..., object], args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, object]:
    bound = inspect.signature(func).bind(*args, **kwargs)
    bound.apply_defaults()

    return dict(bound.arguments)


def key_value(name: str, arguments: dict[str, object], key: str | None) -> str | None:
    if key is None or arguments[key] is None:
        return None

    value = str(arguments[key])
    try:
        return _key_value.validate_python(value)
    except ValidationError:
        raise ValueError(INVALID_KEY_VALUE_ERROR.format(name=name, key=key, value=value)) from None


def trace_arguments(arguments: dict[str, object]) -> dict[str, JsonValue]:
    return {name: to_json_value(value) for name, value in arguments.items() if name not in UNTRACED_ARGUMENT_NAMES}


def to_json_value(value: object) -> JsonValue:
    return to_jsonable_python(value, fallback=repr)
