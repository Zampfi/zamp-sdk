SYNC_CALL_IN_WORKFLOW_ERROR = (
    "{name}: a sync function cannot reach the eval actions from workflow code; make {function} async"
)
GENERATOR_FUNCTION_ERROR = "{name}: {function} is a generator, which a trace cannot record; return the values instead"
EVAL_ACTION_FAILED_ERROR = "{action_name} {action_id} {status}: {error}"
