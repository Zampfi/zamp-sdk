from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ReturnedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["returned"]
    value: JsonValue = Field(
        description="What the call returned as JSON; top-level and container bytes are base64 text, bytes inside a model use the model's own encoding"
    )


class RaisedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["raised"]
    type: str
    message: str


class MockFailedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["mock_failed"]
    code: Literal["MOCK_FAILED"] = "MOCK_FAILED"
    message: str


ExternalCallOutcome: TypeAlias = Annotated[
    ReturnedOutcome | RaisedOutcome | MockFailedOutcome, Field(discriminator="kind")
]
ObservedStepOutcome: TypeAlias = Annotated[ReturnedOutcome | RaisedOutcome, Field(discriminator="kind")]
