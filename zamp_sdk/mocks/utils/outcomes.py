import inspect
import sys
from collections.abc import Callable
from dataclasses import is_dataclass
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ForwardRef,
    Literal,
    NamedTuple,
    cast,
    get_args,
    get_origin,
    is_typeddict,
)

from pydantic import BaseModel, ConfigDict, JsonValue, PydanticSchemaGenerationError, TypeAdapter
from pydantic.errors import PydanticInvalidForJsonSchema

from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.mocks.constants import (
    PLACEHOLDER_REQUEST_METHOD,
    PLACEHOLDER_REQUEST_URL,
    UNBUILDABLE_EXCEPTION_ERROR,
    UNKNOWN_EXCEPTION_TYPE_ERROR,
)
from zamp_sdk.mocks.models import MockHttpResponse, Raised
from zamp_sdk.mocks.utils.errors import MockFailedError

if TYPE_CHECKING:
    import httpx

# Traces write top-level and container bytes as base64, so a return type reads its mock value back the same way.
# A model, dataclass or TypedDict carries its own config, which pydantic will not let this one override.
_BYTES_AS_BASE64 = ConfigDict(val_json_bytes="base64")

_MOCK_HTTP_RESPONSE: TypeAdapter[object] = TypeAdapter(MockHttpResponse)
_MOCK_HTTP_RESPONSE_OR_NONE: TypeAdapter[object] = TypeAdapter(MockHttpResponse | None)


def build_exception(raised: Raised, function_globals: dict[str, Any]) -> Exception:
    module_name, _, class_name = raised.type.rpartition(".")

    # Code run by exec() on the executor has no module in sys.modules, so its own classes are read from its globals
    if module_name == function_globals.get("__name__"):
        error_class = function_globals.get(class_name)
    else:
        # vars() rather than getattr(), so a module's __getattr__ cannot import anything for the mock
        module = sys.modules.get(module_name)
        error_class = vars(module).get(class_name) if module is not None else None

    if isinstance(error_class, type) and issubclass(error_class, Exception):
        return _instantiate(error_class, raised)

    return MockFailedError(UNKNOWN_EXCEPTION_TYPE_ERROR.format(type=raised.type, message=raised.message))


def _instantiate(error_class: type[Exception], raised: Raised) -> Exception:
    try:
        return error_class(raised.message)
    except TypeError:
        pass

    # Classes with required extra arguments (httpx.HTTPStatusError, CalledProcessError) can't take just a message
    try:
        error = error_class.__new__(error_class)
    except TypeError:
        return MockFailedError(UNKNOWN_EXCEPTION_TYPE_ERROR.format(type=raised.type, message=raised.message))
    error.args = (raised.message,)
    # Some (CalledProcessError) build their message from attributes only __init__ sets
    try:
        str(error)
    except Exception:
        return MockFailedError(UNBUILDABLE_EXCEPTION_ERROR.format(type=raised.type, message=raised.message))
    return error


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
    if not _is_httpx_response(annotation):
        return value if adapter is None else adapter.validate_python(value)

    if value is None and annotation is not loaded_httpx.Response:  # type: ignore[union-attr]
        return None

    return _build_httpx_response(loaded_httpx, MockHttpResponse.model_validate(value))  # type: ignore[arg-type]


def output_schema_of(return_type: ReturnType) -> dict[str, JsonValue] | None:
    annotation, adapter = return_type
    if _is_httpx_response(annotation):
        # A Response has no schema of its own; a mock answers it with a MockHttpResponse.
        optional = annotation is not sys.modules["httpx"].Response
        adapter = _MOCK_HTTP_RESPONSE_OR_NONE if optional else _MOCK_HTTP_RESPONSE

    if adapter is None:
        return None

    try:
        return cast(dict[str, JsonValue], adapter.json_schema())
    except PydanticInvalidForJsonSchema:
        return None


def _is_httpx_response(annotation: object) -> bool:
    loaded_httpx = sys.modules.get("httpx")
    return loaded_httpx is not None and annotation in (loaded_httpx.Response, loaded_httpx.Response | None)


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


def _build_httpx_response(loaded_httpx: ModuleType, response: MockHttpResponse) -> "httpx.Response":
    return loaded_httpx.Response(
        response.status,
        headers=response.headers,
        content=response.content,
        text=response.body if isinstance(response.body, str) else None,
        json=None if isinstance(response.body, str) else response.body,
        request=loaded_httpx.Request(PLACEHOLDER_REQUEST_METHOD, PLACEHOLDER_REQUEST_URL),
    )
