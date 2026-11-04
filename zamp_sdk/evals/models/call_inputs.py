from pydantic import BaseModel, ConfigDict, JsonValue

from zamp_sdk.evals.models.outcomes import ObservedStepOutcome


class TracedCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    key: str | None
    invocation_id: str
    parent: str
    args: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None = None
    description: str | None = None


class MockCallInput(TracedCallInput):
    """The mock call's wire payload: `input`/`call_id` are the new names of `args`/`invocation_id`, which stay for older servers."""

    input: dict[str, JsonValue]
    call_id: str


class ObservedStepInput(TracedCallInput):
    outcome: ObservedStepOutcome
