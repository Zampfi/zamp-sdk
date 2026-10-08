from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from zamp_sdk.evals.constants import CALL_NAME_PATTERN, ERROR_TYPE_PATTERN, KEY_VALUE_PATTERN

CallName = Annotated[str, StringConstraints(pattern=CALL_NAME_PATTERN, max_length=100)]
KeyValue = Annotated[str, StringConstraints(pattern=KEY_VALUE_PATTERN)]
FixtureErrorCode = Literal["FIXTURE_MISSING", "FIXTURE_EXHAUSTED"]


class FixtureError(BaseModel):
    """A transport error raised in place of the call, built as type(message)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=ERROR_TYPE_PATTERN)
    message: str = ""


class DoorCall(BaseModel):
    """One decorated call sent to the door: an external asks for its fixture, an observe reports its outcome."""

    kind: Literal["external", "observe"]
    name: CallName
    key: KeyValue | None
    args: dict[str, JsonValue]
    call_id: str
    parent: str
    returns: JsonValue = None
    raises: FixtureError | None = None


class TraceRead(BaseModel):
    """Asks the door for the whole trace of the current execution."""

    kind: Literal["read_trace"] = "read_trace"
