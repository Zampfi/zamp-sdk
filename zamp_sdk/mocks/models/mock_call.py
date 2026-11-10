from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class MockCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(description="The case the call runs under")
    name: str = Field(description="The call's name: an action or skill call name")
    input: dict[str, JsonValue] = Field(description="The call's arguments by name, credentials stripped")
    output_schema: dict[str, JsonValue] | None = Field(
        description="JSON schema of what the call returns; none when unknown"
    )
    call_id: str = Field(description="The call's id; a retry reuses it")


class Returned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["returned"] = Field(description="The call returned")
    value: JsonValue = Field(description="What the call returned")


class Raised(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raised"] = Field(description="The call raised")
    type: str = Field(description="The exception's type name")
    message: str = Field(description="The exception's message")


class MockFailed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mock_failed"] = Field(description="Mocks could not answer; the call fails and is not retried")
    message: str = Field(description="Neutral text the subject sees")


MockOutcome: TypeAlias = Annotated[Returned | Raised | MockFailed, Field(discriminator="kind")]


class RunReal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["run_real"] = Field(description="The real call runs")


class Answered(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["answered"] = Field(description="Mocks answered the call")
    outcome: MockOutcome = Field(description="What the call is answered with")


MockDecision: TypeAlias = Annotated[RunReal | Answered, Field(discriminator="decision")]
