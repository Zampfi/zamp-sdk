from pydantic import BaseModel, JsonValue

from zamp_sdk.action_executor.constants import ActionStatus


class GatewayEnvelope(BaseModel):
    id: str
    status: ActionStatus
    result: JsonValue = None
    error: str | None = None
