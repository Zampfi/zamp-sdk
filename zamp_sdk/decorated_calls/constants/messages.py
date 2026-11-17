SYNC_CALL_ON_ACTIONS_HUB_ERROR = (
    "{name}: a sync function cannot call platform actions from workflow code; make {function} async"
)
GENERATOR_FUNCTION_ERROR = (
    "{name}: {function} is a generator, whose values a platform call cannot carry; return them instead"
)
PLATFORM_ACTION_FAILED_ERROR = "{action_name} {action_id} {status}: {error}"
