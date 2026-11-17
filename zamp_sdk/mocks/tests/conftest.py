import pytest


@pytest.fixture
def answered_returned(answered):
    return lambda value: answered({"kind": "returned", "value": value})


@pytest.fixture
def answered_raised(answered):
    return lambda type, message: answered({"kind": "raised", "type": type, "message": message})


@pytest.fixture
def answered_mock_failed(answered):
    return lambda message: answered({"kind": "mock_failed", "message": message})
