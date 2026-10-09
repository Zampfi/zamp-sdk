import uuid
from collections.abc import Callable

from pydantic import JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import EVAL_ACTION_FAILED_ERROR
from zamp_sdk.evals.models import ExternalCallInput, GatewayEnvelope
from zamp_sdk.evals.utils.arguments import bind_arguments, key_value, trace_arguments


def new_invocation_id() -> str:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        from temporalio import workflow

        return workflow.uuid4().hex

    return uuid.uuid4().hex


def build_call_input(
    name: str,
    key: str | None,
    func: Callable[..., object],
    args: tuple[object, ...],
    kwargs: dict[str, object],
    parent: str,
) -> ExternalCallInput:
    arguments = bind_arguments(func, args, kwargs)

    return ExternalCallInput(
        name=name,
        key=key_value(arguments, key),
        invocation_id=new_invocation_id(),
        parent=parent,
        args=trace_arguments(arguments),
    )


async def send_to_trial(action_name: str, params: dict[str, JsonValue]) -> JsonValue:
    response = await ActionExecutor.execute(action_name, params)

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
