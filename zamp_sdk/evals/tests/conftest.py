import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

ACTION_EXECUTOR_EXECUTE_PATH = "zamp_sdk.action_executor.ActionExecutor.execute"


@pytest.fixture(autouse=True)
def _outside_any_eval_trial(monkeypatch):
    monkeypatch.delenv("ZAMP_SDK_EXECUTION_HOST", raising=False)
    monkeypatch.delenv("ZAMP_EVAL_TRIAL_ID", raising=False)


@pytest.fixture
def in_eval_trial(monkeypatch):
    monkeypatch.setenv("ZAMP_EVAL_TRIAL_ID", "run1-1-item1-1")


@pytest.fixture
def in_eval_trial_on_actions_hub(monkeypatch):
    with _on_actions_hub(monkeypatch, {"eval_trial_id": "run1-1-item1-1"}):
        yield


@pytest.fixture
def on_actions_hub_outside_a_trial(monkeypatch):
    with _on_actions_hub(monkeypatch, {"branch_id": "b1"}):
        yield


@contextmanager
def _on_actions_hub(monkeypatch, metadata):
    monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")
    bound = {"zamp_metadata_context": metadata}
    modules = {
        "zamp_public_workflow_sdk.actions_hub.utils.context_utils": SimpleNamespace(
            get_variable_from_context=bound.get
        ),
        "temporalio": SimpleNamespace(workflow=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="workflow-uuid"))),
    }
    with patch.dict(sys.modules, modules):
        yield


@pytest.fixture
def execute_action():
    with patch(ACTION_EXECUTOR_EXECUTE_PATH, new=AsyncMock()) as execute:
        yield execute


@pytest.fixture
def action_response():
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
def fixture_lookup_failed():
    return lambda code, message: {"kind": "fixture_failed", "code": code, "message": message}
