import functools
import inspect
import sys
import warnings
from collections.abc import Callable
from typing import Any, TypeVar, cast

from pydantic import JsonValue, TypeAdapter
from pydantic.errors import PydanticInvalidForJsonSchema

from zamp_sdk.context import current_eval_trial_id
from zamp_sdk.evals.constants import (
    EVAL_EXTERNAL_CALL_ACTION_NAME,
    EVAL_READ_TRACE_ACTION_NAME,
    EXTERNAL_CALL_DEPRECATED_WARNING,
    GENERATOR_FUNCTION_ERROR,
    KEY_ARGUMENT_NOT_A_PARAMETER_ERROR,
    DecoratedCallKind,
)
from zamp_sdk.evals.models import (
    ExternalCallOutcome,
    MockCallInput,
    MockFailedOutcome,
    RaisedOutcome,
    ReadTraceResult,
    TracedCallInput,
    TraceEntry,
)
from zamp_sdk.evals.utils import (
    MockFailedError,
    ReturnType,
    accepts_argument,
    as_return_type,
    build_exception,
    build_mock_call_input,
    build_traced_call_input,
    call_eval_action,
    parent_of,
    raise_if_on_actions_hub,
    resolve_return_type,
    run_blocking,
    run_observed,
    run_observed_sync,
)

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])

_external_call_outcome_adapter: TypeAdapter[ExternalCallOutcome] = TypeAdapter(ExternalCallOutcome)


def external_call(name: str, key_argument: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    """Deprecated alias of `zamp_sdk.mocks.mockable`; `key_argument` is still checked but no longer sent."""
    warnings.warn(EXTERNAL_CALL_DEPRECATED_WARNING, DeprecationWarning, stacklevel=2)
    return build_decorator(DecoratedCallKind.EXTERNAL_CALL, name, key_argument)


def observe(name: str, key_argument: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    """In an eval trial, run the function and record what it returned or raised in the trace.

    The return value and error message are written as they are, so a function that returns a credential is not observed.
    """
    return build_decorator(DecoratedCallKind.OBSERVED_STEP, name, key_argument)


async def read_trace() -> list[TraceEntry]:
    """The calls this eval trial has traced so far, in order; empty outside a trial."""
    if current_eval_trial_id() is None:
        return []

    return ReadTraceResult.model_validate(await call_eval_action(EVAL_READ_TRACE_ACTION_NAME, {})).entries


def build_decorator(
    kind: DecoratedCallKind,
    name: str,
    key_argument: str | None,
) -> Callable[[_FunctionT], _FunctionT]:
    def decorate(func: _FunctionT) -> _FunctionT:
        if inspect.isgeneratorfunction(func) or inspect.isasyncgenfunction(func):
            raise TypeError(GENERATOR_FUNCTION_ERROR.format(name=name, function=func.__qualname__))

        signature = inspect.signature(func)
        if key_argument is not None and not accepts_argument(signature, key_argument):
            raise TypeError(
                KEY_ARGUMENT_NOT_A_PARAMETER_ERROR.format(
                    name=name, function=func.__qualname__, key_argument=key_argument
                )
            )

        # Read on the first call, not at decoration: a return type may name a class defined after the function.
        @functools.cache
        def return_type() -> ReturnType:
            return resolve_return_type(func)

        @functools.cache
        def output_schema() -> dict[str, JsonValue] | None:
            adapter = return_type().adapter
            if adapter is None:
                return None

            try:
                return cast(dict[str, JsonValue], adapter.json_schema())
            except PydanticInvalidForJsonSchema:
                return None

        def build_mock_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> MockCallInput:
            return build_mock_call_input(name, signature, args, kwargs, output_schema())

        def build_step_call(args: tuple[Any, ...], kwargs: dict[str, Any], parent: str) -> TracedCallInput:
            return build_traced_call_input(name, key_argument, signature, args, kwargs, parent)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_trial_id() is None:
                    return func(*args, **kwargs)

                if kind is DecoratedCallKind.OBSERVED_STEP:
                    # Frame 1 is the caller: the parent unless an observed step encloses it. Cheaper than inspect.stack().
                    step = build_step_call(args, kwargs, parent_of(sys._getframe(1)))
                    return run_observed(step, functools.partial(func, *args, **kwargs))

                return _answer_from_mock(return_type, func.__globals__, build_mock_call(args, kwargs))

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_trial_id() is None:
                return func(*args, **kwargs)

            raise_if_on_actions_hub(name, func)

            if kind is DecoratedCallKind.OBSERVED_STEP:
                step = build_step_call(args, kwargs, parent_of(sys._getframe(1)))
                return run_observed_sync(step, functools.partial(func, *args, **kwargs))

            return run_blocking(_answer_from_mock(return_type, func.__globals__, build_mock_call(args, kwargs)))

        return cast(_FunctionT, call_sync)

    return decorate


async def _answer_from_mock(
    return_type: Callable[[], ReturnType], function_globals: dict[str, Any], call: MockCallInput
) -> Any:
    outcome = _external_call_outcome_adapter.validate_python(
        await call_eval_action(EVAL_EXTERNAL_CALL_ACTION_NAME, call.model_dump(mode="json"))
    )
    if isinstance(outcome, MockFailedOutcome):
        raise MockFailedError(outcome.message)

    if isinstance(outcome, RaisedOutcome):
        raise build_exception(outcome, function_globals)

    return as_return_type(return_type(), outcome.value)
