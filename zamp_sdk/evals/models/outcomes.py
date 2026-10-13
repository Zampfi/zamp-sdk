from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.evals.constants import FixtureErrorCode


# Replies come from the engine, so a field it adds later is ignored rather than failing an older SDK.
class ReturnedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["returned"]
    value: JsonValue = Field(description="What the call returned as JSON; bytes at any depth are base64 text")


class RaisedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["raised"]
    type: str
    message: str


class FixtureLookupFailedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["fixture_failed"]
    code: FixtureErrorCode
    message: str


ExternalCallOutcome: TypeAlias = Annotated[
    ReturnedOutcome | RaisedOutcome | FixtureLookupFailedOutcome, Field(discriminator="kind")
]
ObservedStepOutcome: TypeAlias = Annotated[ReturnedOutcome | RaisedOutcome, Field(discriminator="kind")]
