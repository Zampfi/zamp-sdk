import importlib
import inspect
import sys
from collections.abc import Callable
from types import ModuleType
from typing import TYPE_CHECKING

from pydantic import ConfigDict, JsonValue, TypeAdapter

from zamp_sdk.evals.constants import PLACEHOLDER_REQUEST_METHOD, PLACEHOLDER_REQUEST_URL
from zamp_sdk.evals.models import FixtureResponse, Raised, Returned
from zamp_sdk.evals.utils.arguments import to_json_value

if TYPE_CHECKING:
    import httpx

# Traces write bytes as base64, so a bytes return reads its fixture value back the same way.
_BYTES_AS_BASE64 = ConfigDict(val_json_bytes="base64")


def to_raised(error: Exception) -> Raised:
    return Raised(kind="raised", type=f"{type(error).__module__}.{type(error).__name__}", message=str(error))


def to_returned(result: object) -> Returned:
    return Returned(kind="returned", value=to_json_value(result))


def build_exception(raised: Raised) -> Exception:
    module_name, _, class_name = raised.type.rpartition(".")

    return getattr(importlib.import_module(module_name), class_name)(raised.message)


def returned_value(func: Callable[..., object], value: JsonValue) -> object:
    annotation = _return_annotation(func)
    if annotation is inspect.Signature.empty:
        return value

    loaded_httpx = sys.modules.get("httpx")
    if loaded_httpx is None or annotation not in (loaded_httpx.Response, loaded_httpx.Response | None):
        config = _BYTES_AS_BASE64 if annotation in (bytes, bytes | None) else None

        return TypeAdapter(annotation, config=config).validate_python(value)

    if value is None and annotation is not loaded_httpx.Response:
        return None

    return _build_response(loaded_httpx, FixtureResponse.model_validate(value))


def _return_annotation(func: Callable[..., object]) -> object:
    try:
        return inspect.signature(func, eval_str=True).return_annotation
    except NameError:
        return inspect.Signature.empty


def _build_response(loaded_httpx: ModuleType, response: FixtureResponse) -> "httpx.Response":
    return loaded_httpx.Response(
        response.status,
        headers=response.headers,
        content=response.content,
        text=response.body if isinstance(response.body, str) else None,
        json=None if isinstance(response.body, str) else response.body,
        request=loaded_httpx.Request(PLACEHOLDER_REQUEST_METHOD, PLACEHOLDER_REQUEST_URL),
    )
