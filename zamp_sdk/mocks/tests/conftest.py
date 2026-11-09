import pytest


@pytest.fixture
def returned(answered):
    return lambda value: answered({"kind": "returned", "value": value})


@pytest.fixture
def raised(answered):
    return lambda type, message: answered({"kind": "raised", "type": type, "message": message})


@pytest.fixture
def mock_failed(answered):
    return lambda message: answered({"kind": "mock_failed", "message": message})
