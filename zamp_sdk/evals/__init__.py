"""Fixtures and traces for eval runs.

Outside an eval run a decorated function runs untouched. In one, every call goes through the platform's door
action: an ``external`` returns or raises its fixture instead of running, an ``observe`` runs and is recorded,
and :func:`read_trace` reads back what was recorded.

The public names are defined here rather than re-exported: the code executor exposes only a sub-namespace's own
members.
"""

import functools
import inspect
import sys
import uuid
from contextvars import ContextVar
from types import FrameType
from typing import Any, Callable, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import current_eval_execution_id
from zamp_sdk.evals.constants import EVAL_DOOR_ACTION
from zamp_sdk.evals.models import (
    CallName,
    DoorCall,
    FixtureError,
    FixtureErrorCode,
    KeyValue,
    TraceRead,
)
from zamp_sdk.evals.utils import (
    call_arguments,
    caller,
    error_of,
    exception_from,
    jsonable,
    key_value,
    returned_value,
    run_blocking,
)

_F = TypeVar("_F", bound=Callable[..., Any])

_step: ContextVar[str | None] = ContextVar("zamp_eval_step", default=None)


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
    raises: FixtureError | None = None
    fixture_error: FixtureErrorCode | None = None

    @property
    def id(self) -> str:
        """name[:key]#n, the id error messages use: erp.approval_state#2."""
        return f"{self.name}{f':{self.key}' if self.key is not None else ''}#{self.n}"


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
            raise LookupError(f"{name}: expected one trace line, found {len(found)}")
        return found[0]

    def last(self, name: str, key: str | None = None, **args: JsonValue) -> TraceLine:
        found = self.find(name, key, **args)
        if not found:
            raise LookupError(f"{name}: no trace line")
        return found[-1]


def external(name: str, key: str | None = None) -> Callable[[_F], _F]:
    """In an eval run the call does not run: it returns or raises what the item's fixture says."""

    def decorate(func: _F) -> _F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def run_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_execution_id() is None:
                    return await func(*args, **kwargs)

                call = _door_call("external", name, key, func, args, kwargs, _parent(sys._getframe(1)))
                return _answer(func, await _send(call))

            return cast(_F, run_async)

        @functools.wraps(func)
        def run_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_execution_id() is None:
                return func(*args, **kwargs)

            call = _door_call("external", name, key, func, args, kwargs, _parent(sys._getframe(1)))
            return _answer(func, run_blocking(_send(call)))

        return cast(_F, run_sync)

    return decorate


def observe(name: str, key: str | None = None) -> Callable[[_F], _F]:
    """In an eval run the call runs as usual and its outcome is recorded; calls inside it name it as parent."""

    def decorate(func: _F) -> _F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def run_async(*args: Any, **kwargs: Any) -> Any:
                if current_eval_execution_id() is None:
                    return await func(*args, **kwargs)

                call = _door_call("observe", name, key, func, args, kwargs, _parent(sys._getframe(1)))
                step = _step.set(name)
                try:
                    result = await func(*args, **kwargs)
                except Exception as error:
                    await _send(call.model_copy(update={"raises": error_of(error)}))
                    raise
                finally:
                    _step.reset(step)

                await _send(call.model_copy(update={"returns": jsonable(result)}))
                return result

            return cast(_F, run_async)

        @functools.wraps(func)
        def run_sync(*args: Any, **kwargs: Any) -> Any:
            if current_eval_execution_id() is None:
                return func(*args, **kwargs)

            call = _door_call("observe", name, key, func, args, kwargs, _parent(sys._getframe(1)))
            step = _step.set(name)
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                run_blocking(_send(call.model_copy(update={"raises": error_of(error)})))
                raise
            finally:
                _step.reset(step)

            run_blocking(_send(call.model_copy(update={"returns": jsonable(result)})))
            return result

        return cast(_F, run_sync)

    return decorate


async def read_trace() -> Trace:
    """Every call the current execution made so far, read through the door."""
    return Trace.model_validate(await ActionExecutor.execute(EVAL_DOOR_ACTION, TraceRead().model_dump()))


def _door_call(
    kind: Literal["external", "observe"],
    name: str,
    key: str | None,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    parent: str,
) -> DoorCall:
    arguments = call_arguments(func, args, kwargs)
    return DoorCall(
        kind=kind,
        name=name,
        key=key_value(arguments, key),
        args=arguments,
        call_id=uuid.uuid4().hex,
        parent=parent,
    )


def _parent(frame: FrameType) -> str:
    return _step.get() or caller(frame)


async def _send(call: DoorCall) -> TraceLine:
    return TraceLine.model_validate(await ActionExecutor.execute(EVAL_DOOR_ACTION, call.model_dump(mode="json")))


def _answer(func: Callable[..., Any], line: TraceLine) -> Any:
    if line.fixture_error is not None:
        raise LookupError(f"{line.id}: {line.fixture_error}")
    if line.raises is not None:
        raise exception_from(line.raises)
    return returned_value(func, line.returns)
