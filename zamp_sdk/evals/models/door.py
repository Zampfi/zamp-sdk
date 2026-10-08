from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from zamp_sdk.evals.constants import (
    CALL_NAME_PATTERN,
    ERROR_TYPE_PATTERN,
    KEY_VALUE_PATTERN,
    REPLY_OUTCOME_COUNT_ERROR,
    REPLY_OUTCOME_FIELDS,
    DoorKind,
)

CallName: TypeAlias = Annotated[str, StringConstraints(pattern=CALL_NAME_PATTERN, max_length=100)]
KeyValue: TypeAlias = Annotated[str, StringConstraints(pattern=KEY_VALUE_PATTERN)]
FixtureErrorCode: TypeAlias = Literal["FIXTURE_MISSING", "FIXTURE_EXHAUSTED"]


class RaisedError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=ERROR_TYPE_PATTERN)
    message: str = ""


class StepCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[DoorKind.EXTERNAL, DoorKind.OBSERVE]
    call_id: str
    name: CallName
    key: KeyValue | None
    parent: str
    args: dict[str, JsonValue]
    returns: JsonValue = None
    raises: RaisedError | None = None


class ReadTraceCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[DoorKind.READ_TRACE] = DoorKind.READ_TRACE
    call_id: str


class DoorReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=1)
    returns: JsonValue = None
    raises: RaisedError | None = None
    fixture_error: FixtureErrorCode | None = None

    @model_validator(mode="after")
    def _has_exactly_one_outcome(self) -> Self:
        if len(self.model_fields_set & REPLY_OUTCOME_FIELDS) != 1:
            raise ValueError(REPLY_OUTCOME_COUNT_ERROR)

        return self


class GatewayEnvelope(BaseModel):
    id: str
    status: str
    result: JsonValue = None
    error: str | None = None
