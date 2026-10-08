import uuid
from collections.abc import Callable

from pydantic import BaseModel, JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import EVAL_ACTION_FAILED_ERROR, FixtureAndTraceOperation
from zamp_sdk.evals.models import EvalFixtureAndTraceInput, GatewayEnvelope
from zamp_sdk.evals.utils.arguments import bind_arguments, key_value, trace_arguments


def new_call_id() -> str:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        from temporalio import workflow

        return workflow.uuid4().hex

    return uuid.uuid4().hex


def build_step_call(
    kind: FixtureAndTraceOperation,
    name: str,
    key: str | None,
    func: Callable[..., object],
    args: tuple[object, ...],
    kwargs: dict[str, object],
    parent: str,
) -> EvalFixtureAndTraceInput:
    arguments = bind_arguments(func, args, kwargs)

    return EvalFixtureAndTraceInput(
        kind=kind,
        call_id=new_call_id(),
        name=name,
        key=key_value(arguments, key),
        parent=parent,
        args=trace_arguments(arguments),
    )


async def send_to_trial(action_name: str, request: BaseModel) -> JsonValue:
    response = await ActionExecutor.execute(action_name, request.model_dump(mode="json"))

    # The executor's gateway returns {id, status, result, error} and reports a failure as a value
    if not (isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response)):
        return response

    envelope = GatewayEnvelope.model_validate(response)
    if envelope.status not in SUCCESS_STATUSES:
        raise RuntimeError(
            EVAL_ACTION_FAILED_ERROR.format(
                action_name=action_name, action_id=envelope.id, status=envelope.status, error=envelope.error
            )
        )

    return envelope.result
