import os
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from types import FrameType

from zamp_sdk.evals.models import EvalFixtureAndTraceInput
from zamp_sdk.evals.utils.arguments import to_json_value
from zamp_sdk.evals.utils.blocking import ResultT, run_blocking
from zamp_sdk.evals.utils.fixture_and_trace import send_to_trial
from zamp_sdk.evals.utils.outcomes import to_raised_error

_enclosing_observe_name: ContextVar[str | None] = ContextVar("zamp_eval_enclosing_observe", default=None)


def parent_of(frame: FrameType) -> str:
    return _enclosing_observe_name.get() or f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}"


async def run_observed(call: EvalFixtureAndTraceInput, invoke: Callable[[], Awaitable[ResultT]]) -> ResultT:
    reset_token = _enclosing_observe_name.set(call.name)
    try:
        result = await invoke()
    except Exception as error:
        await send_to_trial(call.model_copy(update={"raises": to_raised_error(error)}))
        raise
    finally:
        _enclosing_observe_name.reset(reset_token)

    await send_to_trial(call.model_copy(update={"returns": to_json_value(result)}))

    return result


def run_observed_sync(call: EvalFixtureAndTraceInput, invoke: Callable[[], ResultT]) -> ResultT:
    reset_token = _enclosing_observe_name.set(call.name)
    try:
        result = invoke()
    except Exception as error:
        run_blocking(send_to_trial(call.model_copy(update={"raises": to_raised_error(error)})))
        raise
    finally:
        _enclosing_observe_name.reset(reset_token)

    run_blocking(send_to_trial(call.model_copy(update={"returns": to_json_value(result)})))

    return result
