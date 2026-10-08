import inspect
from collections.abc import Callable
from typing import Annotated

from pydantic import JsonValue, Strict, StrictInt, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from zamp_sdk.evals.constants import (
    INVALID_CALL_NAME_ERROR,
    INVALID_KEY_VALUE_ERROR,
    KEY_NOT_A_PARAMETER_ERROR,
    UNTRACED_ARGUMENT_NAMES,
)
from zamp_sdk.evals.models import CallName, KeyValue

_call_name_adapter = TypeAdapter(CallName)
_key_value_adapter: TypeAdapter[str | int] = TypeAdapter(Annotated[KeyValue, Strict()] | StrictInt)


def raise_if_invalid_decoration(name: str, key: str | None, func: Callable[..., object]) -> None:
    try:
        _call_name_adapter.validate_python(name)
    except ValidationError:
        raise ValueError(INVALID_CALL_NAME_ERROR.format(name=name)) from None

    if key is not None and key not in inspect.signature(func).parameters:
        raise ValueError(KEY_NOT_A_PARAMETER_ERROR.format(name=name, key=key, function=func.__qualname__))


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


def key_value(name: str, arguments: dict[str, object], key: str | None) -> str | None:
    if key is None:
        return None

    try:
        return str(_key_value_adapter.validate_python(arguments[key]))
    except ValidationError:
        raise ValueError(INVALID_KEY_VALUE_ERROR.format(name=name, key=key, value=arguments[key])) from None


def trace_arguments(arguments: dict[str, object]) -> dict[str, JsonValue]:
    return {name: to_json_value(value) for name, value in arguments.items() if name not in UNTRACED_ARGUMENT_NAMES}


def to_json_value(value: object) -> JsonValue:
    try:
        return to_jsonable_python(value, fallback=repr)
    except ValueError:
        return repr(value)
