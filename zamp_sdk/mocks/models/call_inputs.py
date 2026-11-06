from pydantic import BaseModel, ConfigDict, JsonValue


class MockCallInput(BaseModel):
    """What a mockable call sends the platform: nothing but these four fields."""

    model_config = ConfigDict(extra="forbid")

    name: str
    input: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None
    call_id: str
