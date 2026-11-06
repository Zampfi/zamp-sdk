from zamp_sdk.mocks.utils.errors import MockFailedError
from zamp_sdk.mocks.utils.mock_calls import answer_from_mock, build_mock_call_input
from zamp_sdk.mocks.utils.outcomes import (
    ReturnType,
    as_return_type,
    build_exception,
    output_schema_of,
    resolve_return_type,
)

__all__ = [
    "MockFailedError",
    "ReturnType",
    "answer_from_mock",
    "as_return_type",
    "build_exception",
    "build_mock_call_input",
    "output_schema_of",
    "resolve_return_type",
]
