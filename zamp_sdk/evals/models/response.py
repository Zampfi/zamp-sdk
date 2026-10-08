from typing import Self

from pydantic import Base64Bytes, BaseModel, ConfigDict, Field, JsonValue, model_validator

from zamp_sdk.evals.constants import BODY_AND_CONTENT_ERROR


class FixtureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int
    body: JsonValue = None
    content: Base64Bytes | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_body_or_content(self) -> Self:
        if self.body is not None and self.content is not None:
            raise ValueError(BODY_AND_CONTENT_ERROR)

        return self
