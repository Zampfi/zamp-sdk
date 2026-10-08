import functools
import inspect
import sys
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, Field, JsonValue

from zamp_sdk.context import current_eval_trial_id
from zamp_sdk.evals.constants import (
    FIXTURE_ERROR_MESSAGE,
    NO_TRACE_LINE_ERROR,
    TRACE_LINE_COUNT_ERROR,
    FixtureAndTraceOperation,
)
from zamp_sdk.evals.models import (
    CallName,
    EvalFixtureAndTraceInput,
    EvalReadTraceInput,
    FixtureErrorCode,
    FixtureReply,
    KeyValue,
    RaisedError,
)
from zamp_sdk.evals.utils import (
    build_exception,
    build_step_call,
    line_id,
    new_call_id,
    parent_of,
    raise_if_workflow_host,
    returned_value,
    run_blocking,
    run_observed,
    run_observed_sync,
    send_to_trial,
)
from zamp_sdk.logging.constants import EVAL_FIXTURE_AND_TRACE_ACTION_NAME, EVAL_READ_TRACE_ACTION_NAME

__all__ = ["FixtureError", "Trace", "TraceLine", "external", "observe", "read_trace"]

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


class FixtureError(Exception):
    pass


class TraceLine(BaseModel):
    """One decorated call in one trial. The platform's eval_fixture_and_trace action writes it as the call goes
    through; collect reads it back with read_trace()."""

    kind: Literal["external", "observe"]
    name: CallName
    key: KeyValue | None = Field(
        default=None, description="Value of the parameter the decorator names as key, if it names one"
    )
    n: int = Field(ge=1, description="Calls of this name and key so far in the trial, this one included")
    parent: str = Field(description="Enclosing observe step, else file:function; for reading only, never matched")
    args: dict[str, JsonValue] = Field(description="Arguments by name; headers and credentials are never written")
    returns: JsonValue = None
    raises: RaisedError | None = None
    fixture_error: FixtureErrorCode | None = None

    @property
    def id(self) -> str:
        return line_id(self.name, self.key, self.n)


class Trace(BaseModel):
    """One trial's trace, read by collect. Lines are picked by name, key and args; last is the latest repeated call."""

    lines: list[TraceLine]

    def find(self, name: str, key: str | None = None, **args: JsonValue) -> list[TraceLine]:
        return [
            line
            for line in self.lines
            if line.name == name
            and (key is None or line.key == key)
            and all(line.args.get(arg) == value for arg, value in args.items())
        ]

    def one(self, name: str, key: str | None = None, **args: JsonValue) -> TraceLine:
        found = self.find(name, key, **args)
        if len(found) != 1:
            raise LookupError(TRACE_LINE_COUNT_ERROR.format(name=name, count=len(found)))

        return found[0]

    def last(self, name: str, key: str | None = None, **args: JsonValue) -> TraceLine:
        found = self.find(name, key, **args)
        if not found:
            raise LookupError(NO_TRACE_LINE_ERROR.format(name=name))

        return found[-1]


def external(name: str, key: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    return _decorator(FixtureAndTraceOperation.REPLAY_FIXTURE, name, key)


def observe(name: str, key: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    return _decorator(FixtureAndTraceOperation.RECORD_STEP, name, key)


async def read_trace() -> Trace:
    request = EvalReadTraceInput(call_id=new_call_id())

    return Trace.model_validate(await send_to_trial(EVAL_READ_TRACE_ACTION_NAME, request))


def _decorator(
    kind: FixtureAndTraceOperation,
    name: str,
    key: str | None,
) -> Callable[[_FunctionT], _FunctionT]:
    def decorate(func: _FunctionT) -> _FunctionT:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_trial_id() is None:
                    return func(*args, **kwargs)

                call = build_step_call(kind, name, key, func, args, kwargs, parent_of(sys._getframe(1)))
                if kind is FixtureAndTraceOperation.RECORD_STEP:
                    return run_observed(call, functools.partial(func, *args, **kwargs))

                return _answer_from_fixture(func, call)

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_trial_id() is None:
                return func(*args, **kwargs)

            raise_if_workflow_host(name, func)

            call = build_step_call(kind, name, key, func, args, kwargs, parent_of(sys._getframe(1)))
            if kind is FixtureAndTraceOperation.RECORD_STEP:
                return run_observed_sync(call, functools.partial(func, *args, **kwargs))

            return run_blocking(_answer_from_fixture(func, call))

        return cast(_FunctionT, call_sync)

    return decorate


async def _answer_from_fixture(func: Callable[..., Any], call: EvalFixtureAndTraceInput) -> Any:
    reply = FixtureReply.model_validate(await send_to_trial(EVAL_FIXTURE_AND_TRACE_ACTION_NAME, call))
    if reply.fixture_error is not None:
        raise FixtureError(
            FIXTURE_ERROR_MESSAGE.format(
                line_id=line_id(call.name, call.key, reply.n), fixture_error=reply.fixture_error
            )
        )

    if reply.raises is not None:
        raise build_exception(reply.raises)

    return returned_value(func, call.name, reply.returns)
