from pydantic import BaseModel, ConfigDict, Field, JsonValue


# Replies come from the engine, so a field it adds later is ignored rather than failing an older SDK.
class FixtureHttpResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", val_json_bytes="base64")

    status: int
    body: JsonValue = None
    content: bytes | None = None
    headers: dict[str, str] = Field(default_factory=dict)
