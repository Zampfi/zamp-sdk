from pydantic import BaseModel, ConfigDict, Field, JsonValue


class FixtureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", val_json_bytes="base64")

    status: int
    body: JsonValue = None
    content: bytes | None = None
    headers: dict[str, str] = Field(default_factory=dict)
