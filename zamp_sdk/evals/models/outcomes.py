from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.evals.constants import FixtureErrorCode


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


class FixtureFailedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["fixture_failed"]
    code: FixtureErrorCode
    message: str


ExternalCallOutcome: TypeAlias = Annotated[
    ReturnedOutcome | RaisedOutcome | FixtureFailedOutcome, Field(discriminator="kind")
]
ObservedStepOutcome: TypeAlias = Annotated[ReturnedOutcome | RaisedOutcome, Field(discriminator="kind")]
