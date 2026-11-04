from collections.abc import Callable
from typing import Any, TypeVar

from zamp_sdk.evals.constants import DecoratedCallKind
from zamp_sdk.evals.evals import build_decorator

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def mockable(name: str) -> Callable[[_FunctionT], _FunctionT]:
    """In an eval trial, answer the call from a mock instead of running it; outside one, run it as written.

    The fixture key comes from server-side config. The return type's JSON schema and the docstring are sent along.
    """
    return build_decorator(DecoratedCallKind.EXTERNAL_CALL, name, None)
