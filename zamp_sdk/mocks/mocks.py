import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from pydantic import JsonValue

from zamp_sdk.calls.utils import raise_if_on_actions_hub, reject_generator, run_blocking
from zamp_sdk.context import current_mock_case_id
from zamp_sdk.mocks.models import RunReal
from zamp_sdk.mocks.utils import (
    ReturnType,
    act_out,
    ask_mocks,
    build_mock_call,
    output_schema_of,
    resolve_return_type,
)

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def mockable(name: str) -> Callable[[_FunctionT], _FunctionT]:
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
            async def call_async(*args: Any, **kwargs: Any) -> Any:
                case_id = current_mock_case_id()
                if case_id is None:
                    return await func(*args, **kwargs)

                decision = await ask_mocks(build_mock_call(case_id, name, signature, args, kwargs, output_schema()))
                if isinstance(decision, RunReal):
                    return await func(*args, **kwargs)

                return act_out(decision.outcome, return_type(), func.__globals__)

            return cast(_FunctionT, call_async)

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            case_id = current_mock_case_id()
            if case_id is None:
                return func(*args, **kwargs)

            raise_if_on_actions_hub(name, func)

            decision = run_blocking(ask_mocks(build_mock_call(case_id, name, signature, args, kwargs, output_schema())))
            if isinstance(decision, RunReal):
                return func(*args, **kwargs)

            return act_out(decision.outcome, return_type(), func.__globals__)

        return cast(_FunctionT, call_sync)

    return decorate
