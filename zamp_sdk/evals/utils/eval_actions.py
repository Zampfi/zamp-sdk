import inspect
import uuid

from pydantic import JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.action_executor.models.action_response import ActionResponse
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import EVAL_ACTION_FAILED_ERROR
from zamp_sdk.evals.models import TracedCallInput
from zamp_sdk.evals.utils.arguments import arguments_to_trace, bind_arguments, key_from_arguments


def new_invocation_id() -> str:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        from temporalio import workflow

        return workflow.uuid4().hex

    return uuid.uuid4().hex


def build_traced_call_input(
    name: str,
    key_argument: str | None,
    signature: inspect.Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    parent: str,
) -> TracedCallInput:
    arguments = bind_arguments(signature, args, kwargs)

    return TracedCallInput(
        name=name,
        key=key_from_arguments(arguments, key_argument),
        invocation_id=new_invocation_id(),
        parent=parent,
        args=arguments_to_trace(arguments),
    )


async def call_eval_action(action_name: str, params: dict[str, JsonValue]) -> JsonValue:
    response = await ActionExecutor.execute(action_name, params)

    # A failed action arrives as a returned value, not an exception
    if not (isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response)):
        return response

    action_response = ActionResponse.model_validate(response)
    if action_response.status not in SUCCESS_STATUSES:
        raise RuntimeError(
            EVAL_ACTION_FAILED_ERROR.format(
                action_name=action_name,
                action_id=action_response.id,
                status=action_response.status,
                error=action_response.error,
            )
        )

    return action_response.result
