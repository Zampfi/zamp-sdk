from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from zamp_sdk.action_executor.constants import ActionStatus
from zamp_sdk.evals.constants import (
    CALL_NAME_PATTERN,
    ERROR_TYPE_PATTERN,
    KEY_VALUE_PATTERN,
    FixtureAndTraceOperation,
)

CallName: TypeAlias = Annotated[str, StringConstraints(pattern=CALL_NAME_PATTERN, max_length=100)]
KeyValue: TypeAlias = Annotated[str, StringConstraints(pattern=KEY_VALUE_PATTERN)]
FixtureErrorCode: TypeAlias = Literal["FIXTURE_MISSING", "FIXTURE_EXHAUSTED"]


class RaisedError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=ERROR_TYPE_PATTERN)
    message: str = ""


class EvalFixtureAndTraceInput(BaseModel):
    """One request to the eval_fixture_and_trace action."""

    model_config = ConfigDict(extra="forbid")

    kind: FixtureAndTraceOperation
    call_id: str
    name: CallName
    key: KeyValue | None
    parent: str
    args: dict[str, JsonValue]
    returns: JsonValue = None
    raises: RaisedError | None = None


class EvalReadTraceInput(BaseModel):
    """One request to the eval_read_trace action."""

    model_config = ConfigDict(extra="forbid")

    call_id: str


class GatewayEnvelope(BaseModel):
    id: str
    status: ActionStatus
    result: JsonValue = None
    error: str | None = None


class FixtureReply(BaseModel):
    n: int = Field(ge=1)
    returns: JsonValue = None
    raises: RaisedError | None = None
    fixture_error: FixtureErrorCode | None = None
