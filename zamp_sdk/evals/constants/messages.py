SYNC_CALL_ON_ACTIONS_HUB_ERROR = (
    "{name}: a sync function cannot reach the eval actions from workflow code; make {function} async"
)
GENERATOR_FUNCTION_ERROR = "{name}: {function} is a generator, which a trace cannot record; return the values instead"
KEY_ARGUMENT_NOT_A_PARAMETER_ERROR = "{name}: {function} has no parameter {key_argument} to read the key from"
EVAL_ACTION_FAILED_ERROR = "{action_name} {action_id} {status}: {error}"
STEP_ERROR_NOT_TRACED_MESSAGE = "{name}: the eval trace did not record this error, because {error}"
