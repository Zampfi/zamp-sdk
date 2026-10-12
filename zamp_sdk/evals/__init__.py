import functools
import inspect
import sys
from collections.abc import Callable
from typing import Any, TypeVar, cast

from pydantic import TypeAdapter

from zamp_sdk.context import current_eval_trial_id
from zamp_sdk.evals.constants import DecoratedCallKind
from zamp_sdk.evals.models import (
    ExternalCallOutcome,
    FixtureLookupFailed,
    Raised,
    ReadTraceResult,
    TracedCallInput,
    TraceEntry,
)
from zamp_sdk.evals.utils import (
    build_call_input,
    build_exception,
    parent_of,
    returned_value,
    run_blocking,
    run_observed,
    run_observed_sync,
    send_to_trial,
)
from zamp_sdk.logging.constants import EVAL_EXTERNAL_CALL_ACTION_NAME, EVAL_READ_TRACE_ACTION_NAME

__all__ = ["FixtureLookupError", "TraceEntry", "external", "observe", "read_trace"]

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])

_external_call_outcome: TypeAdapter[ExternalCallOutcome] = TypeAdapter(ExternalCallOutcome)


class FixtureLookupError(Exception):
    pass


def external(name: str, key: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    return _decorator(DecoratedCallKind.EXTERNAL, name, key)


def observe(name: str, key: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    return _decorator(DecoratedCallKind.OBSERVE, name, key)


async def read_trace() -> list[TraceEntry]:
    return ReadTraceResult.model_validate(await send_to_trial(EVAL_READ_TRACE_ACTION_NAME, {})).entries


def _decorator(
    kind: DecoratedCallKind,
    name: str,
    key: str | None,
) -> Callable[[_FunctionT], _FunctionT]:
    def decorate(func: _FunctionT) -> _FunctionT:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_trial_id() is None:
                    return func(*args, **kwargs)

                call = build_call_input(name, key, func, args, kwargs, parent_of(sys._getframe(1)))
                if kind is DecoratedCallKind.OBSERVE:
                    return run_observed(call, functools.partial(func, *args, **kwargs))

                return _answer_from_fixture(func, call)

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_trial_id() is None:
                return func(*args, **kwargs)

            call = build_call_input(name, key, func, args, kwargs, parent_of(sys._getframe(1)))
            if kind is DecoratedCallKind.OBSERVE:
                return run_observed_sync(call, functools.partial(func, *args, **kwargs))

            return run_blocking(_answer_from_fixture(func, call))

        return cast(_FunctionT, call_sync)

    return decorate


async def _answer_from_fixture(func: Callable[..., Any], call: TracedCallInput) -> Any:
    outcome = _external_call_outcome.validate_python(
        await send_to_trial(EVAL_EXTERNAL_CALL_ACTION_NAME, call.model_dump(mode="json"))
    )
    if isinstance(outcome, FixtureLookupFailed):
        raise FixtureLookupError(outcome.message)

    if isinstance(outcome, Raised):
        raise build_exception(outcome)

    return returned_value(func, call.name, outcome.value)
