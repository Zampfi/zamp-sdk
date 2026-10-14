from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.evals.models.outcomes import ExternalCallOutcome, ObservedStepOutcome


class TracedCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    key: str | None = Field(description="Value of the argument the decorator names as key_argument, if it names one")
    call_number: int = Field(ge=1, description="Calls of this name and key so far in the trial, this one included")
    invocation_id: str = Field(
        description="Id the SDK gives this call; a retry of the call has the same id, so it keeps its call_number"
    )
    parent: str = Field(description="Enclosing observe step, else file:function; for reading only, never matched")
    args: dict[str, JsonValue] = Field(
        description=(
            "Arguments by name; self, cls and credential names (token, api_key, headers, ... or ending in _token,"
            " _secret, _password, _api_key or _credentials; any case) are never written"
        )
    )
    recorded_at: datetime


class ExternalCall(TracedCall):
    kind: Literal["external"]
    outcome: ExternalCallOutcome


class ObservedStep(TracedCall):
    kind: Literal["observe"]
    outcome: ObservedStepOutcome


TraceEntry: TypeAlias = Annotated[ExternalCall | ObservedStep, Field(discriminator="kind")]


class ReadTraceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entries: list[TraceEntry]
