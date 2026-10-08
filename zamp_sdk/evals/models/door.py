from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from zamp_sdk.evals.constants import (
    CALL_NAME_PATTERN,
    ERROR_TYPE_PATTERN,
    KEY_VALUE_PATTERN,
    REPLY_OUTCOME_COUNT_ERROR,
    DoorKind,
)

CallName: TypeAlias = Annotated[str, StringConstraints(pattern=CALL_NAME_PATTERN, max_length=100)]
KeyValue: TypeAlias = Annotated[str, StringConstraints(pattern=KEY_VALUE_PATTERN)]
FixtureErrorCode: TypeAlias = Literal["FIXTURE_MISSING", "FIXTURE_EXHAUSTED"]


class RaisedError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=ERROR_TYPE_PATTERN)
    message: str = ""


class DoorCall(BaseModel):
    """One call to the door action. A read_trace call has no name, key, parent or args."""

    model_config = ConfigDict(extra="forbid")

    kind: DoorKind
    call_id: str
    name: CallName | None
    key: KeyValue | None
    parent: str | None
    args: dict[str, JsonValue]
    returns: JsonValue = None
    raises: RaisedError | None = None


class GatewayEnvelope(BaseModel):
    id: str
    status: str
    result: JsonValue = None
    error: str | None = None


class DoorReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=1)
    returns: JsonValue = None
    raises: RaisedError | None = None
    fixture_error: FixtureErrorCode | None = None

    @model_validator(mode="after")
    def _has_one_outcome_at_most(self) -> Self:
        if sum(outcome is not None for outcome in (self.returns, self.raises, self.fixture_error)) > 1:
            raise ValueError(REPLY_OUTCOME_COUNT_ERROR)

        return self
