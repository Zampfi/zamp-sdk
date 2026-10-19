from pydantic import BaseModel, ConfigDict, Field, JsonValue


class FixtureHttpResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", val_json_bytes="base64")

    status: int
    body: JsonValue = None
    content: bytes | None = None
    headers: dict[str, str] = Field(default_factory=dict)
