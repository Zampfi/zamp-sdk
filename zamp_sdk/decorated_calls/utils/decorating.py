import inspect
from collections.abc import Callable

from zamp_sdk.decorated_calls.constants import GENERATOR_FUNCTION_ERROR


def reject_generator(name: str, func: Callable[..., object]) -> None:
    if inspect.isgeneratorfunction(func) or inspect.isasyncgenfunction(func):
        raise TypeError(GENERATOR_FUNCTION_ERROR.format(name=name, function=func.__qualname__))
