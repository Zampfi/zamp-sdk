from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class MockCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    name: str
    input: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None
    call_id: str


class Returned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["returned"]
    value: JsonValue


class Raised(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raised"]
    type: str
    message: str


class MockFailed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mock_failed"]
    message: str


MockOutcome: TypeAlias = Annotated[Returned | Raised | MockFailed, Field(discriminator="kind")]


class RunReal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["run_real"]


class Answered(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["answered"]
    outcome: MockOutcome


MockDecision: TypeAlias = Annotated[RunReal | Answered, Field(discriminator="decision")]
