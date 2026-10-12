from pydantic import BaseModel, JsonValue

from zamp_sdk.action_executor.constants import ActionStatus


class ActionResponse(BaseModel):
    """What the executor's action gateway returns for one action: a failure comes back as a value, not raised."""

    id: str
    status: ActionStatus
    result: JsonValue = None
    error: str | None = None
