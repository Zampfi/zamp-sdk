import importlib
import inspect
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import JsonValue, TypeAdapter

from zamp_sdk.evals.constants import FIXTURE_REQUEST_METHOD, FIXTURE_REQUEST_URL
from zamp_sdk.evals.models import FixtureResponse, RaisedError

if TYPE_CHECKING:
    import httpx


def line_id(name: str, key: str | None, n: int) -> str:
    return f"{name}{f':{key}' if key is not None else ''}#{n}"


def to_raised_error(error: Exception) -> RaisedError:
    return RaisedError(type=f"{type(error).__module__}.{type(error).__name__}", message=str(error))


def build_exception(raised: RaisedError) -> Exception:
    module_name, _, class_name = raised.type.rpartition(".")

    return getattr(importlib.import_module(module_name), class_name)(raised.message)


def returned_value(func: Callable[..., object], name: str, returns: JsonValue) -> object:
    annotation = inspect.signature(func, eval_str=True).return_annotation
    if annotation is inspect.Signature.empty:
        return returns

    if not _returns_httpx_response(annotation):
        return TypeAdapter(annotation).validate_python(returns)

    if returns is None:
        return None

    return _build_response(name, FixtureResponse.model_validate(returns))


def _returns_httpx_response(annotation: object) -> bool:
    httpx = sys.modules.get("httpx")

    return httpx is not None and annotation in (httpx.Response, httpx.Response | None)


def _build_response(name: str, response: FixtureResponse) -> "httpx.Response":
    import httpx

    return httpx.Response(
        response.status,
        headers=response.headers,
        content=response.content,
        text=response.body if isinstance(response.body, str) else None,
        json=None if isinstance(response.body, str) else response.body,
        request=httpx.Request(FIXTURE_REQUEST_METHOD, FIXTURE_REQUEST_URL.format(name=name)),
    )
