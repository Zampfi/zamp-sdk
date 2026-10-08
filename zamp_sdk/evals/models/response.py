from pydantic import Base64Bytes, BaseModel, ConfigDict, Field, JsonValue


class FixtureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int
    body: JsonValue = None
    content: Base64Bytes | None = None
    headers: dict[str, str] = Field(default_factory=dict)
