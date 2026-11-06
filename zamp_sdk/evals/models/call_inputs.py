from pydantic import BaseModel, ConfigDict, JsonValue

from zamp_sdk.evals.models.outcomes import ObservedStepOutcome


class TracedCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    key: str | None
    invocation_id: str
    parent: str
    args: dict[str, JsonValue]


class MockCallInput(BaseModel):
    """What a mockable call sends the platform: nothing but these four fields."""

    model_config = ConfigDict(extra="forbid")

    name: str
    input: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None
    call_id: str


class ObservedStepInput(TracedCallInput):
    outcome: ObservedStepOutcome
