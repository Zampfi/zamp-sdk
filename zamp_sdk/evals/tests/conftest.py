from unittest.mock import AsyncMock, patch

import pytest

EXECUTE = "zamp_sdk.evals.ActionExecutor.execute"


@pytest.fixture(autouse=True)
def _api_host(monkeypatch):
    monkeypatch.delenv("ZAMP_SDK_EXECUTION_HOST", raising=False)
    monkeypatch.delenv("ZAMP_EVAL_EXECUTION_ID", raising=False)


@pytest.fixture
def eval_run(monkeypatch):
    monkeypatch.setenv("ZAMP_EVAL_EXECUTION_ID", "run1-1-item1-1")


@pytest.fixture
def door():
    with patch(EXECUTE, new=AsyncMock()) as execute:
        yield execute


@pytest.fixture
def reply():
    """A door reply: the trace line the platform wrote for the call."""

    def build(kind="external", name="erp.order", key=None, n=1, **fields):
        return {"kind": kind, "name": name, "key": key, "n": n, "parent": "x.py:f", "args": {}, **fields}

    return build
