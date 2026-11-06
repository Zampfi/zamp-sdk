from collections.abc import Callable
from typing import Any, TypeVar

from zamp_sdk.evals import build_decorator
from zamp_sdk.evals.constants import DecoratedCallKind

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def mockable(name: str) -> Callable[[_FunctionT], _FunctionT]:
    """In an eval trial, answer the call from a mock instead of running it; outside one, run it as written.

    The call sends only its name, its arguments as `input`, the return type's JSON schema and a `call_id`; the
    platform decides the reply from its own mock config.
    """
    return build_decorator(DecoratedCallKind.EXTERNAL_CALL, name, None)
