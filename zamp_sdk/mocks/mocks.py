import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from pydantic import JsonValue

from zamp_sdk.context import current_eval_trial_id
from zamp_sdk.evals.utils import raise_if_on_actions_hub, reject_generator, run_blocking
from zamp_sdk.mocks.utils import (
    ReturnType,
    answer_from_mock,
    build_mock_call_input,
    output_schema_of,
    resolve_return_type,
)

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def mockable(name: str) -> Callable[[_FunctionT], _FunctionT]:
    """In an eval trial, answer the call from a mock instead of running it; outside one, run it as written.

    The call sends only its name, its arguments as `input`, the return type's JSON schema and a `call_id`; the
    platform decides the reply from its own mock config.
    """

    def decorate(func: _FunctionT) -> _FunctionT:
        reject_generator(name, func)

        signature = inspect.signature(func)

        # Read on the first call, not at decoration: a return type may name a class defined after the function.
        @functools.cache
        def return_type() -> ReturnType:
            return resolve_return_type(func)

        @functools.cache
        def output_schema() -> dict[str, JsonValue] | None:
            return output_schema_of(return_type())

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_trial_id() is None:
                    return func(*args, **kwargs)

                call = build_mock_call_input(name, signature, args, kwargs, output_schema())
                return answer_from_mock(return_type, func.__globals__, call)

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_trial_id() is None:
                return func(*args, **kwargs)

            raise_if_on_actions_hub(name, func)

            call = build_mock_call_input(name, signature, args, kwargs, output_schema())
            return run_blocking(answer_from_mock(return_type, func.__globals__, call))

        return cast(_FunctionT, call_sync)

    return decorate
