import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import DOOR_FAILED_ERROR, DoorKind
from zamp_sdk.evals.models import DoorCall, GatewayEnvelope
from zamp_sdk.evals.utils.arguments import bind_arguments, key_value, trace_arguments
from zamp_sdk.logging.constants import EVAL_DOOR_ACTION_NAME


def new_call_id() -> str:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        from temporalio import workflow

        return workflow.uuid4().hex

    return uuid.uuid4().hex


def build_step_call(
    kind: Literal[DoorKind.EXTERNAL, DoorKind.OBSERVE],
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
        key=key_value(name, arguments, key),
        parent=parent,
        args=trace_arguments(arguments),
    )


def build_read_trace_call() -> DoorCall:
    return DoorCall(kind=DoorKind.READ_TRACE, call_id=new_call_id(), name=None, key=None, parent=None, args={})


async def send_door_call(call: DoorCall) -> JsonValue:
    response = await ActionExecutor.execute(EVAL_DOOR_ACTION_NAME, call.model_dump(mode="json"))

    # The executor's gateway returns {id, status, result, error} and reports a failure as a value
    if not (isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response)):
        return response

    envelope = GatewayEnvelope.model_validate(response)
    if envelope.status not in SUCCESS_STATUSES:
        raise RuntimeError(
            DOOR_FAILED_ERROR.format(action_id=envelope.id, status=envelope.status, error=envelope.error)
        )

    return envelope.result
