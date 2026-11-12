from zamp_sdk.decorated_calls.utils import to_json_value
from zamp_sdk.evals.models import RaisedOutcome, ReturnedOutcome


def to_raised(error: Exception) -> RaisedOutcome:
    # str() of a KeyError adds quotes around its key
    message = str(error.args[0]) if isinstance(error, KeyError) and error.args else str(error)

    return RaisedOutcome(kind="raised", type=f"{type(error).__module__}.{type(error).__name__}", message=message)


def to_returned(result: object) -> ReturnedOutcome:
    return ReturnedOutcome(kind="returned", value=to_json_value(result))
