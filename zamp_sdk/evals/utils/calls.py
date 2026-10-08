import importlib
import inspect
import os
import sys
from types import FrameType, ModuleType
from typing import Any, Callable

from pydantic import JsonValue, TypeAdapter
from pydantic_core import to_jsonable_python

from zamp_sdk.evals.models import FixtureError


def call_arguments(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, JsonValue]:
    bound = inspect.signature(func).bind(*args, **kwargs)
    bound.apply_defaults()
    return {name: jsonable(value) for name, value in bound.arguments.items()}


def key_value(arguments: dict[str, JsonValue], key: str | None) -> str | None:
    if key is None or arguments[key] is None:
        return None
    return str(arguments[key])


def caller(frame: FrameType) -> str:
    return f"{os.path.relpath(frame.f_code.co_filename)}:{frame.f_code.co_name}"


def jsonable(value: Any) -> JsonValue:
    return to_jsonable_python(value, fallback=str)


def error_of(error: Exception) -> FixtureError:
    return FixtureError(type=f"{type(error).__module__}.{type(error).__name__}", message=str(error))


def exception_from(error: FixtureError) -> Exception:
    module_name, _, class_name = error.type.rpartition(".")
    return getattr(importlib.import_module(module_name), class_name)(error.message)


def returned_value(func: Callable[..., Any], returns: JsonValue) -> Any:
    """The fixture's returns as the decorated function's return type: httpx.Response from {status, body, headers}."""
    annotation = inspect.signature(func, eval_str=True).return_annotation
    if annotation is inspect.Signature.empty:
        return returns

    httpx = sys.modules.get("httpx")
    if httpx is not None and annotation is httpx.Response:
        return _response(httpx, returns)
    return TypeAdapter(annotation).validate_python(returns)


def _response(httpx: ModuleType, returns: Any) -> Any:
    body = returns.get("body")
    content = {"text": body} if isinstance(body, str) else {"json": body}
    return httpx.Response(returns["status"], headers=returns.get("headers"), **content)
