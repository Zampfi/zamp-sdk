from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.evals.constants import FixtureErrorCode


class Returned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["returned"]
    value: JsonValue


class Raised(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raised"]
    type: str
    message: str


class FixtureFailed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fixture_failed"]
    code: FixtureErrorCode
    message: str


ExternalCallOutcome: TypeAlias = Annotated[Returned | Raised | FixtureFailed, Field(discriminator="kind")]
ObservedOutcome: TypeAlias = Annotated[Returned | Raised, Field(discriminator="kind")]
