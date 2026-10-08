INVALID_CALL_NAME_ERROR = (
    "{name!r} is not a call name; use service.operation in lowercase letters, digits and underscores"
)
KEY_NOT_A_PARAMETER_ERROR = "{name}: key '{key}' is not a parameter of {function}; name one of its parameters"
INVALID_KEY_VALUE_ERROR = "{name}: key '{key}' is {value!r}; a key value has no spaces or '#'"
SYNC_CALL_IN_WORKFLOW_ERROR = (
    "{name}: a sync function cannot reach the eval door from workflow code; make {function} async"
)
DOOR_FAILED_ERROR = "Action {action_id} {status}: {error}"
REPLY_OUTCOME_COUNT_ERROR = "a door reply carries exactly one of returns, raises or fixture_error"
BODY_AND_CONTENT_ERROR = "a fixture response has a body or content, not both"
FIXTURE_ERROR_MESSAGE = "{line_id}: {fixture_error}"
TRACE_LINE_COUNT_ERROR = "{name}: expected one trace line, found {count}"
NO_TRACE_LINE_ERROR = "{name}: no trace line"
