import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

EXECUTE = "zamp_sdk.action_executor.ActionExecutor.execute"


class ZampMetadataContext(BaseModel):
    eval_trial_id: str | None = None


@pytest.fixture(autouse=True)
def _api_host(monkeypatch):
    monkeypatch.delenv("ZAMP_SDK_EXECUTION_HOST", raising=False)
    monkeypatch.delenv("ZAMP_EVAL_TRIAL_ID", raising=False)


@pytest.fixture
def eval_run(monkeypatch):
    monkeypatch.setenv("ZAMP_EVAL_TRIAL_ID", "run1-1-item1-1")


@pytest.fixture
def executor_eval_run(monkeypatch):
    monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")
    bound = {"zamp_metadata_context": {"eval_trial_id": "run1-1-item1-1"}}
    modules = {
        "zamp_public_workflow_sdk.actions_hub.models.common_models": SimpleNamespace(
            ZampMetadataContext=ZampMetadataContext
        ),
        "zamp_public_workflow_sdk.actions_hub.utils.context_utils": SimpleNamespace(
            get_variable_from_context=bound.get
        ),
        "temporalio": SimpleNamespace(workflow=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="workflow-uuid"))),
    }
    with patch.dict(sys.modules, modules):
        yield


@pytest.fixture
def fixtures_and_trace():
    with patch(EXECUTE, new=AsyncMock()) as execute:
        yield execute


@pytest.fixture
def envelope():
    def build(result=None, status="COMPLETED", error=None):
        return {"id": "action-1", "status": status, "result": result, "error": error}

    return build


@pytest.fixture
def returned():
    return lambda value: {"kind": "returned", "value": value}


@pytest.fixture
def raised():
    return lambda type, message: {"kind": "raised", "type": type, "message": message}


@pytest.fixture
def fixture_failed():
    return lambda code, message: {"kind": "fixture_failed", "code": code, "message": message}
