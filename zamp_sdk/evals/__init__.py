import functools
import inspect
import sys
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.context import current_eval_execution_id
from zamp_sdk.evals.constants import FIXTURE_ERROR_MESSAGE, NO_TRACE_LINE_ERROR, TRACE_LINE_COUNT_ERROR, DoorKind
from zamp_sdk.evals.models import CallName, DoorCall, DoorReply, FixtureErrorCode, KeyValue, RaisedError
from zamp_sdk.evals.utils import (
    build_door_call,
    build_exception,
    build_read_trace_call,
    line_id,
    parent_of,
    raise_if_key_not_a_parameter,
    raise_if_workflow_host,
    returned_value,
    run_blocking,
    run_observed,
    run_observed_sync,
    send_door_call,
)

_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


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
    def decorate(func: _FunctionT) -> _FunctionT:
        raise_if_key_not_a_parameter(name, key, func)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_execution_id() is None:
                    return func(*args, **kwargs)

                call = build_door_call(DoorKind.EXTERNAL, name, key, func, args, kwargs, parent_of(sys._getframe(1)))

                return _return_or_raise_fixture(func, name, call)

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_execution_id() is None:
                return func(*args, **kwargs)

            raise_if_workflow_host(name, func)
            call = build_door_call(DoorKind.EXTERNAL, name, key, func, args, kwargs, parent_of(sys._getframe(1)))

            return run_blocking(_return_or_raise_fixture(func, name, call))

        return cast(_FunctionT, call_sync)

    return decorate


def observe(name: str, key: str | None = None) -> Callable[[_FunctionT], _FunctionT]:
    def decorate(func: _FunctionT) -> _FunctionT:
        raise_if_key_not_a_parameter(name, key, func)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            def call_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_execution_id() is None:
                    return func(*args, **kwargs)

                call = build_door_call(DoorKind.OBSERVE, name, key, func, args, kwargs, parent_of(sys._getframe(1)))

                return run_observed(func, call, args, kwargs)

            return cast(_FunctionT, inspect.markcoroutinefunction(call_async))

        @functools.wraps(func)
        def call_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_execution_id() is None:
                return func(*args, **kwargs)

            raise_if_workflow_host(name, func)
            call = build_door_call(DoorKind.OBSERVE, name, key, func, args, kwargs, parent_of(sys._getframe(1)))

            return run_observed_sync(func, call, args, kwargs)

        return cast(_FunctionT, call_sync)

    return decorate


async def read_trace() -> Trace:
    return Trace.model_validate(await send_door_call(build_read_trace_call()))


async def _return_or_raise_fixture(func: Callable[..., object], name: str, call: DoorCall) -> object:
    reply = DoorReply.model_validate(await send_door_call(call))
    if reply.fixture_error is not None:
        raise FixtureError(
            FIXTURE_ERROR_MESSAGE.format(line_id=line_id(name, call.key, reply.n), fixture_error=reply.fixture_error)
        )

    if reply.raises is not None:
        raise build_exception(reply.raises)

    return returned_value(func, name, reply.returns)
