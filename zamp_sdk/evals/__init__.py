import functools
import inspect
import sys
from collections.abc import Callable, Coroutine
from typing import Any, Literal, TypeAlias, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.context import current_eval_execution_id
from zamp_sdk.evals.constants import FIXTURE_ERROR_MESSAGE, NO_TRACE_LINE_ERROR, TRACE_LINE_COUNT_ERROR, DoorKind
from zamp_sdk.evals.models import CallName, DoorReply, FixtureErrorCode, KeyValue, RaisedError, StepCall
from zamp_sdk.evals.utils import (
    build_exception,
    build_read_trace_call,
    build_step_call,
    line_id,
    parent_of,
    raise_if_invalid_decoration,
    raise_if_workflow_host,
    returned_value,
    run_blocking,
    run_observed,
    run_observed_sync,
    send_door_call,
)

__all__ = ["FixtureError", "Trace", "TraceLine", "external", "observe", "read_trace"]

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])
_AsyncRunner: TypeAlias = Callable[
    [Callable[..., Any], StepCall, tuple[Any, ...], dict[str, Any]], Coroutine[Any, Any, Any]
]
_SyncRunner: TypeAlias = Callable[[Callable[..., Any], StepCall, tuple[Any, ...], dict[str, Any]], Any]


class FixtureError(Exception):
    pass


class TraceLine(BaseModel):
    """One decorated call in one execution. The platform's door action writes it as the call goes through and holds
    the trace; collect and the engine read it."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["external", "observe"]
    name: CallName
    key: KeyValue | None = Field(
        default=None, description="Value of the parameter the decorator names as key, if it names one"
    )
    n: int = Field(ge=1, description="Calls of this name and key so far in the execution, this one included")
    parent: str = Field(description="Enclosing observe step, else file:function; for reading only, never matched")
    args: dict[str, JsonValue] = Field(description="Arguments by name; headers and credentials are never written")
    returns: JsonValue = None
    raises: RaisedError | None = None
    fixture_error: FixtureErrorCode | None = None

    @property
    def id(self) -> str:
        return line_id(self.name, self.key, self.n)


class Trace(BaseModel):
    """One execution's trace, which collect reads through the door action. Lines are picked by name, never by line order."""

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
    return _decorator(DoorKind.EXTERNAL, name, key, _return_or_raise_fixture, _return_or_raise_fixture_sync)


def observe(name: str, key: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    return _decorator(DoorKind.OBSERVE, name, key, run_observed, run_observed_sync)


async def read_trace() -> Trace:
    return Trace.model_validate(await send_door_call(build_read_trace_call()))


def _decorator(
    kind: Literal[DoorKind.EXTERNAL, DoorKind.OBSERVE],
    name: str,
    key: str | None,
    run_async: _AsyncRunner,
    run_sync: _SyncRunner,
) -> Callable[[_FunctionT], _FunctionT]:
    def decorate(func: _FunctionT) -> _FunctionT:
        raise_if_invalid_decoration(name, key, func)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_execution_id() is None:
                    return func(*args, **kwargs)

                call = build_step_call(kind, name, key, func, args, kwargs, parent_of(sys._getframe(1)))

                return run_async(func, call, args, kwargs)

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_execution_id() is None:
                return func(*args, **kwargs)

            raise_if_workflow_host(name, func)
            call = build_step_call(kind, name, key, func, args, kwargs, parent_of(sys._getframe(1)))

            return run_sync(func, call, args, kwargs)

        return cast(_FunctionT, call_sync)

    return decorate


async def _return_or_raise_fixture(
    func: Callable[..., Any], call: StepCall, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    reply = DoorReply.model_validate(await send_door_call(call))
    if reply.fixture_error is not None:
        raise FixtureError(
            FIXTURE_ERROR_MESSAGE.format(
                line_id=line_id(call.name, call.key, reply.n), fixture_error=reply.fixture_error
            )
        )

    if reply.raises is not None:
        raise build_exception(reply.raises)

    return returned_value(func, call.name, reply.returns)


def _return_or_raise_fixture_sync(
    func: Callable[..., Any], call: StepCall, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    return run_blocking(_return_or_raise_fixture(func, call, args, kwargs))
