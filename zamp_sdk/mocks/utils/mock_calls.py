import inspect
from typing import Any

from pydantic import JsonValue, TypeAdapter, ValidationError

from zamp_sdk.calls.constants import MOCK_CALL_ACTION_NAME
from zamp_sdk.calls.utils import arguments_without_credentials, bind_arguments, call_platform_action, new_call_id
from zamp_sdk.context import without_mock_case
from zamp_sdk.mocks.constants import MOCKED_VALUE_UNFIT_ERROR, UNKNOWN_MOCK_REPLY_ERROR
from zamp_sdk.mocks.models import MockCall, MockDecision, MockFailed, MockOutcome, Raised
from zamp_sdk.mocks.utils.errors import MockFailedError
from zamp_sdk.mocks.utils.outcomes import ReturnType, as_return_type, build_exception

_mock_decision_adapter: TypeAdapter[MockDecision] = TypeAdapter(MockDecision)


def build_mock_call(
    case_id: str,
    name: str,
    signature: inspect.Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    output_schema: dict[str, JsonValue] | None,
) -> MockCall:
    return MockCall(
        case_id=case_id,
        name=name,
        input=arguments_without_credentials(bind_arguments(signature, args, kwargs)),
        output_schema=output_schema,
        call_id=new_call_id(),
    )


async def ask_mocks(call: MockCall) -> MockDecision:
    with without_mock_case():
        reply = await call_platform_action(MOCK_CALL_ACTION_NAME, call.model_dump(mode="json"))
    try:
        return _mock_decision_adapter.validate_python(reply)
    except ValidationError as error:
        raise MockFailedError(UNKNOWN_MOCK_REPLY_ERROR.format(name=call.name)) from error


def act_out(outcome: MockOutcome, return_type: ReturnType, function_globals: dict[str, Any]) -> Any:
    if isinstance(outcome, MockFailed):
        raise MockFailedError(outcome.message)

    if isinstance(outcome, Raised):
        raise build_exception(outcome, function_globals)

    try:
        return as_return_type(return_type, outcome.value)
    except ValidationError:
        raise MockFailedError(MOCKED_VALUE_UNFIT_ERROR) from None
