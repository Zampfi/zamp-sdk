import inspect
import sys
from collections.abc import Callable
from dataclasses import is_dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Annotated, ForwardRef, Literal, NamedTuple, get_args, get_origin, is_typeddict

from pydantic import BaseModel, ConfigDict, JsonValue, PydanticSchemaGenerationError, TypeAdapter

from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import (
    PLACEHOLDER_REQUEST_METHOD,
    PLACEHOLDER_REQUEST_URL,
    UNKNOWN_EXCEPTION_TYPE_ERROR,
)
from zamp_sdk.evals.models import FixtureHttpResponse, RaisedOutcome, ReturnedOutcome
from zamp_sdk.evals.utils.arguments import to_json_value
from zamp_sdk.evals.utils.errors import FixtureLookupError

if TYPE_CHECKING:
    import httpx

# Traces write top-level and container bytes as base64, so a return type reads its fixture value back the same way.
# A model, dataclass or TypedDict carries its own config, which pydantic will not let this one override.
_BYTES_AS_BASE64 = ConfigDict(val_json_bytes="base64")


def to_raised(error: Exception) -> RaisedOutcome:
    # str() of a KeyError adds quotes around its key
    message = str(error.args[0]) if isinstance(error, KeyError) and error.args else str(error)

    return RaisedOutcome(kind="raised", type=f"{type(error).__module__}.{type(error).__name__}", message=message)


def to_returned(result: object) -> ReturnedOutcome:
    return ReturnedOutcome(kind="returned", value=to_json_value(result))


def build_exception(raised: RaisedOutcome) -> Exception:
    module_name, _, class_name = raised.type.rpartition(".")

    # vars() rather than getattr(), so a module's __getattr__ cannot import anything for the fixture
    module = sys.modules.get(module_name)
    error_class = vars(module).get(class_name) if module is not None else None
    if isinstance(error_class, type) and issubclass(error_class, Exception):
        return error_class(raised.message)

    return FixtureLookupError(UNKNOWN_EXCEPTION_TYPE_ERROR.format(type=raised.type, message=raised.message))


class ReturnType(NamedTuple):
    annotation: object
    adapter: TypeAdapter[object] | None


def resolve_return_type(func: Callable[..., object]) -> ReturnType:
    annotation = _return_annotation(func)
    if annotation is inspect.Signature.empty:
        return ReturnType(annotation, None)

    config = None if _has_own_config(annotation) else _BYTES_AS_BASE64
    try:
        return ReturnType(annotation, TypeAdapter(annotation, config=config))
    except PydanticSchemaGenerationError:
        return ReturnType(annotation, None)


def as_return_type(return_type: ReturnType, value: JsonValue) -> object:
    annotation, adapter = return_type
    if annotation is inspect.Signature.empty:
        return value

    loaded_httpx = sys.modules.get("httpx")
    if loaded_httpx is None or annotation not in (loaded_httpx.Response, loaded_httpx.Response | None):
        return value if adapter is None else adapter.validate_python(value)

    if value is None and annotation is not loaded_httpx.Response:
        return None

    return _build_httpx_response(loaded_httpx, FixtureHttpResponse.model_validate(value))


def _contains_string(annotation: object) -> bool:
    if isinstance(annotation, str | ForwardRef):
        return True

    origin = get_origin(annotation)
    if origin is Literal:
        return False

    args = get_args(annotation)
    # Annotated metadata is never evaluated, only the type it wraps
    if origin is Annotated:
        args = args[:1]

    return any(_contains_string(arg) for arg in args)


def _has_own_config(annotation: object) -> bool:
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]

    return isinstance(annotation, type) and (
        issubclass(annotation, BaseModel) or is_dataclass(annotation) or is_typeddict(annotation)
    )


def _return_annotation(func: Callable[..., object]) -> object:
    annotation = inspect.get_annotations(func).get("return", inspect.Signature.empty)

    # On the executor, evaluating a string anywhere in the annotation would run skill code outside the merge-time check.
    if current_execution_host() is ExecutionHost.ACTIONS_HUB and _contains_string(annotation):
        return inspect.Signature.empty

    if not isinstance(annotation, str):
        return annotation

    try:
        return eval(annotation, func.__globals__)
    except NameError:
        return inspect.Signature.empty


def _build_httpx_response(loaded_httpx: ModuleType, response: FixtureHttpResponse) -> "httpx.Response":
    return loaded_httpx.Response(
        response.status,
        headers=response.headers,
        content=response.content,
        text=response.body if isinstance(response.body, str) else None,
        json=None if isinstance(response.body, str) else response.body,
        request=loaded_httpx.Request(PLACEHOLDER_REQUEST_METHOD, PLACEHOLDER_REQUEST_URL),
    )
