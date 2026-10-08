import uuid
from collections.abc import Callable

from pydantic import JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import EVAL_DOOR_ACTION, DoorKind
from zamp_sdk.evals.models import DoorCall
from zamp_sdk.evals.utils.arguments import bind_arguments, key_value, trace_arguments


def new_call_id() -> str:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        from temporalio import workflow

        return workflow.uuid4().hex

    return uuid.uuid4().hex


def build_door_call(
    kind: DoorKind,
    name: str,
    key: str | None,
    func: Callable[..., object],
    args: tuple[object, ...],
    kwargs: dict[str, object],
    parent: str,
) -> DoorCall:
    arguments = bind_arguments(func, args, kwargs)

    return DoorCall(
        kind=kind,
        call_id=new_call_id(),
        name=name,
        key=key_value(arguments, key),
        parent=parent,
        args=trace_arguments(arguments),
    )


def build_read_trace_call() -> DoorCall:
    return DoorCall(kind=DoorKind.READ_TRACE, call_id=new_call_id(), name=None, key=None, parent=None, args={})


async def send_door_call(call: DoorCall) -> JsonValue:
    return await ActionExecutor.execute(EVAL_DOOR_ACTION, call.model_dump(mode="json"))
