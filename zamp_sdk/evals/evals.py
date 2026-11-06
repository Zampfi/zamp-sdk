import functools
import inspect
import sys
from collections.abc import Callable
from typing import Any, TypeVar, cast

from zamp_sdk.context import current_eval_trial_id
from zamp_sdk.evals.constants import EVAL_READ_TRACE_ACTION_NAME, KEY_ARGUMENT_NOT_A_PARAMETER_ERROR
from zamp_sdk.evals.models import ReadTraceResult, TraceEntry
from zamp_sdk.evals.utils import (
    accepts_argument,
    build_traced_call_input,
    call_eval_action,
    parent_of,
    raise_if_on_actions_hub,
    reject_generator,
    run_observed,
    run_observed_sync,
)

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def observe(name: str, key_argument: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    """In an eval trial, run the function and record what it returned or raised in the trace.

    The return value and error message are written as they are, so a function that returns a credential is not observed.
    """

    def decorate(func: _FunctionT) -> _FunctionT:
        reject_generator(name, func)

        signature = inspect.signature(func)
        if key_argument is not None and not accepts_argument(signature, key_argument):
            raise TypeError(
                KEY_ARGUMENT_NOT_A_PARAMETER_ERROR.format(
                    name=name, function=func.__qualname__, key_argument=key_argument
                )
            )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_trial_id() is None:
                    return func(*args, **kwargs)

                # Frame 1 is the caller: the parent unless an observed step encloses it. Cheaper than inspect.stack().
                step = build_traced_call_input(name, key_argument, signature, args, kwargs, parent_of(sys._getframe(1)))
                return run_observed(step, functools.partial(func, *args, **kwargs))

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_trial_id() is None:
                return func(*args, **kwargs)

            raise_if_on_actions_hub(name, func)

            step = build_traced_call_input(name, key_argument, signature, args, kwargs, parent_of(sys._getframe(1)))
            return run_observed_sync(step, functools.partial(func, *args, **kwargs))

        return cast(_FunctionT, call_sync)

    return decorate


async def read_trace() -> list[TraceEntry]:
    """The calls this eval trial has traced so far, in order; empty outside a trial."""
    if current_eval_trial_id() is None:
        return []

    return ReadTraceResult.model_validate(await call_eval_action(EVAL_READ_TRACE_ACTION_NAME, {})).entries
