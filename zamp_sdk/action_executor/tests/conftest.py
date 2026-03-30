import pytest


@pytest.fixture
def base_url():
    return "https://api.zamp.test"


@pytest.fixture
def auth_token():
    return "test-token-abc123"
