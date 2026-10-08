INVALID_CALL_NAME_ERROR = (
    "{name!r} is not a call name; use service.operation in lowercase letters, digits and underscores"
)
KEY_NOT_A_PARAMETER_ERROR = "{name}: key '{key}' is not a parameter of {function}; name one of its parameters"
INVALID_KEY_VALUE_ERROR = (
    "{name}: key '{key}' is {value!r}; a key value is an integer or a string with no spaces or '#'"
)
SYNC_CALL_IN_WORKFLOW_ERROR = (
    "{name}: a sync function cannot reach eval_fixture_and_trace from workflow code; make {function} async"
)
REPLY_OUTCOME_COUNT_ERROR = "a fixture reply carries at most one of returns, raises or fixture_error"
FIXTURE_AND_TRACE_FAILED_ERROR = "Action {action_id} {status}: {error}"
BODY_AND_CONTENT_ERROR = "a fixture response has a body or content, not both"
FIXTURE_ERROR_MESSAGE = "{line_id}: {fixture_error}"
TRACE_LINE_COUNT_ERROR = "{name}: expected one trace line, found {count}"
NO_TRACE_LINE_ERROR = "{name}: no trace line"
