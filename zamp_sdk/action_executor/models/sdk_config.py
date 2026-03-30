from pydantic import BaseModel


class SdkConfig(BaseModel):
    """Resolved configuration for the Zamp API."""

    base_url: str
    auth_token: str
