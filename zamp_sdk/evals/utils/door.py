import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import DOOR_FAILED_ERROR, EVAL_DOOR_ACTION, DoorKind
from zamp_sdk.evals.models import GatewayEnvelope, ReadTraceCall, StepCall
from zamp_sdk.evals.utils.arguments import bind_arguments, key_value, trace_arguments


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
) -> StepCall:
    arguments = bind_arguments(func, args, kwargs)

    return StepCall(
        kind=kind,
        call_id=new_call_id(),
        name=name,
        key=key_value(name, arguments, key),
        parent=parent,
        args=trace_arguments(arguments),
    )


def build_read_trace_call() -> ReadTraceCall:
    return ReadTraceCall(call_id=new_call_id())


async def send_door_call(call: StepCall | ReadTraceCall) -> JsonValue:
    response = await ActionExecutor.execute(EVAL_DOOR_ACTION, call.model_dump(mode="json"), log_action=False)
    if not (isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response)):
        return response

    envelope = GatewayEnvelope.model_validate(response)
    if envelope.status not in SUCCESS_STATUSES:
        raise RuntimeError(
            DOOR_FAILED_ERROR.format(action_id=envelope.id, status=envelope.status, error=envelope.error)
        )

    return envelope.result
