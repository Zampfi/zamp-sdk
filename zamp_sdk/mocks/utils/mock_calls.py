import inspect
from collections.abc import Callable
from typing import Any

from pydantic import JsonValue, TypeAdapter

from zamp_sdk.constants import MOCK_CALL_ACTION_NAME
from zamp_sdk.evals.models import ExternalCallOutcome, MockFailedOutcome, RaisedOutcome
from zamp_sdk.evals.utils import arguments_to_trace, bind_arguments, call_eval_action, new_call_id
from zamp_sdk.mocks.models import MockCallInput
from zamp_sdk.mocks.utils.errors import MockFailedError
from zamp_sdk.mocks.utils.outcomes import ReturnType, as_return_type, build_exception

_external_call_outcome_adapter: TypeAdapter[ExternalCallOutcome] = TypeAdapter(ExternalCallOutcome)


def build_mock_call_input(
    name: str,
    signature: inspect.Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    output_schema: dict[str, JsonValue] | None,
) -> MockCallInput:
    return MockCallInput(
        name=name,
        input=arguments_to_trace(bind_arguments(signature, args, kwargs)),
        output_schema=output_schema,
        call_id=new_call_id(),
    )


async def answer_from_mock(
    return_type: Callable[[], ReturnType], function_globals: dict[str, Any], call: MockCallInput
) -> Any:
    outcome = _external_call_outcome_adapter.validate_python(
        await call_eval_action(MOCK_CALL_ACTION_NAME, call.model_dump(mode="json"))
    )
    if isinstance(outcome, MockFailedOutcome):
        raise MockFailedError(outcome.message)

    if isinstance(outcome, RaisedOutcome):
        raise build_exception(outcome, function_globals)

    return as_return_type(return_type(), outcome.value)
