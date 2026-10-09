from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, JsonValue, StringConstraints

from zamp_sdk.evals.constants import CALL_NAME_PATTERN, KEY_VALUE_PATTERN
from zamp_sdk.evals.models.outcomes import ObservedOutcome

CallName: TypeAlias = Annotated[str, StringConstraints(pattern=CALL_NAME_PATTERN, max_length=100)]
KeyValue: TypeAlias = Annotated[str, StringConstraints(pattern=KEY_VALUE_PATTERN)]


class ExternalCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CallName
    key: KeyValue | None
    invocation_id: str
    parent: str
    args: dict[str, JsonValue]


class ObservedStepInput(ExternalCallInput):
    outcome: ObservedOutcome
