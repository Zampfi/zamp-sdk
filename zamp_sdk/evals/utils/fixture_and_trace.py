import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import JsonValue

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import FIXTURE_AND_TRACE_FAILED_ERROR, FixtureAndTraceOperation
from zamp_sdk.evals.models import EvalFixtureAndTraceInput, GatewayEnvelope
from zamp_sdk.evals.utils.arguments import bind_arguments, key_value, trace_arguments
from zamp_sdk.logging.constants import EVAL_FIXTURE_AND_TRACE_ACTION_NAME


def new_call_id() -> str:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        from temporalio import workflow

        return workflow.uuid4().hex

    return uuid.uuid4().hex


def build_step_call(
    kind: Literal[FixtureAndTraceOperation.REPLAY_FIXTURE, FixtureAndTraceOperation.RECORD_STEP],
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
        key=key_value(name, arguments, key),
        parent=parent,
        args=trace_arguments(arguments),
    )


def build_read_trace_call() -> EvalFixtureAndTraceInput:
    return EvalFixtureAndTraceInput(
        kind=FixtureAndTraceOperation.READ_TRACE, call_id=new_call_id(), name=None, key=None, parent=None, args={}
    )


async def send_to_trial(call: EvalFixtureAndTraceInput) -> JsonValue:
    response = await ActionExecutor.execute(EVAL_FIXTURE_AND_TRACE_ACTION_NAME, call.model_dump(mode="json"))

    # The executor's gateway returns {id, status, result, error} and reports a failure as a value
    if not (isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response)):
        return response

    envelope = GatewayEnvelope.model_validate(response)
    if envelope.status not in SUCCESS_STATUSES:
        raise RuntimeError(
            FIXTURE_AND_TRACE_FAILED_ERROR.format(action_id=envelope.id, status=envelope.status, error=envelope.error)
        )

    return envelope.result
