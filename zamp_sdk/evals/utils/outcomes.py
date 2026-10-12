import importlib
import inspect
import sys
from collections.abc import Callable
from dataclasses import is_dataclass
from types import ModuleType
from typing import TYPE_CHECKING, is_typeddict

from pydantic import BaseModel, ConfigDict, JsonValue, PydanticSchemaGenerationError, TypeAdapter

from zamp_sdk.evals.constants import PLACEHOLDER_REQUEST_METHOD, PLACEHOLDER_REQUEST_URL
from zamp_sdk.evals.models import FixtureResponse, Raised, Returned
from zamp_sdk.evals.utils.arguments import to_json_value

if TYPE_CHECKING:
    import httpx

# Traces write bytes as base64 at any depth, so a return type reads its fixture value back the same way. A model,
# dataclass or TypedDict carries its own config, which pydantic will not let this one override.
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
        return _validate_as_annotation(annotation, value)

    if value is None and annotation is not loaded_httpx.Response:
        return None

    return _build_response(loaded_httpx, FixtureResponse.model_validate(value))


def _validate_as_annotation(annotation: object, value: JsonValue) -> object:
    config = None if _has_own_config(annotation) else _BYTES_AS_BASE64
    try:
        adapter: TypeAdapter[object] = TypeAdapter(annotation, config=config)
    except PydanticSchemaGenerationError:
        return value

    return adapter.validate_python(value)


def _has_own_config(annotation: object) -> bool:
    return isinstance(annotation, type) and (
        issubclass(annotation, BaseModel) or is_dataclass(annotation) or is_typeddict(annotation)
    )


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
