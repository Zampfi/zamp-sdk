import os
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from types import FrameType

from pydantic import JsonValue

from zamp_sdk.evals.models import ExternalCallInput, ObservedOutcome, ObservedStepInput, Returned
from zamp_sdk.evals.utils.arguments import to_json_value
from zamp_sdk.evals.utils.blocking import ResultT, run_blocking
from zamp_sdk.evals.utils.outcomes import to_raised
from zamp_sdk.evals.utils.trial_actions import send_to_trial
from zamp_sdk.logging.constants import EVAL_OBSERVED_STEP_ACTION_NAME

_enclosing_observe_name: ContextVar[str | None] = ContextVar("zamp_eval_enclosing_observe", default=None)


def parent_of(frame: FrameType) -> str:
    return _enclosing_observe_name.get() or f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}"


async def run_observed(call: ExternalCallInput, invoke: Callable[[], Awaitable[ResultT]]) -> ResultT:
    reset_token = _enclosing_observe_name.set(call.name)
    try:
        result = await invoke()
    except Exception as error:
        await send_to_trial(EVAL_OBSERVED_STEP_ACTION_NAME, _observed_step_params(call, to_raised(error)))
        raise
    finally:
        _enclosing_observe_name.reset(reset_token)

    await send_to_trial(EVAL_OBSERVED_STEP_ACTION_NAME, _observed_step_params(call, _returned(result)))

    return result


def run_observed_sync(call: ExternalCallInput, invoke: Callable[[], ResultT]) -> ResultT:
    reset_token = _enclosing_observe_name.set(call.name)
    try:
        result = invoke()
    except Exception as error:
        run_blocking(send_to_trial(EVAL_OBSERVED_STEP_ACTION_NAME, _observed_step_params(call, to_raised(error))))
        raise
    finally:
        _enclosing_observe_name.reset(reset_token)

    run_blocking(send_to_trial(EVAL_OBSERVED_STEP_ACTION_NAME, _observed_step_params(call, _returned(result))))

    return result


def _returned(result: object) -> Returned:
    return Returned(kind="returned", value=to_json_value(result))


def _observed_step_params(call: ExternalCallInput, outcome: ObservedOutcome) -> dict[str, JsonValue]:
    return ObservedStepInput(**call.model_dump(), outcome=outcome).model_dump(mode="json")
