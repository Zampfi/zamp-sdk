from pydantic import BaseModel, ConfigDict, JsonValue

from zamp_sdk.evals.models.outcomes import ObservedOutcome


class ExternalCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    key: str | None
    invocation_id: str
    parent: str
    args: dict[str, JsonValue]


class ObservedStepInput(ExternalCallInput):
    outcome: ObservedOutcome
