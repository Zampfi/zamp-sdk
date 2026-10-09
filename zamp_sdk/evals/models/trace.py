from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from zamp_sdk.evals.models.call_inputs import CallName, KeyValue
from zamp_sdk.evals.models.outcomes import ExternalCallOutcome, ObservedOutcome


class TracedCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CallName
    key: KeyValue | None = Field(
        default=None, description="Value of the parameter the decorator names as key, if it names one"
    )
    n: int = Field(ge=1, description="Calls of this name and key so far in the trial, this one included")
    invocation_id: str
    parent: str = Field(description="Enclosing observe step, else file:function; for reading only, never matched")
    args: dict[str, JsonValue] = Field(description="Arguments by name; headers and credentials are never written")
    at: datetime


class ExternalCall(TracedCall):
    kind: Literal["external"]
    outcome: ExternalCallOutcome


class ObservedStep(TracedCall):
    kind: Literal["observe"]
    outcome: ObservedOutcome


TraceLine: TypeAlias = Annotated[ExternalCall | ObservedStep, Field(discriminator="kind")]


class ReadTraceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[TraceLine]
