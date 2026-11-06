"""Fixtures shared by every package's tests.

Logging state: both switches live in context variables that outlive a single test in the same task,
so without a reset one test's `configure_logging` silently changes what the next one asserts. At the
root rather than per package: the state is shared, so resetting it should be too. The environment
variable is cleared for the same reason.

Metadata context: on the actions hub the executor binds a dict that `zamp_sdk.context` and
`zamp_sdk.evals` and `zamp_sdk.mocks` read, so the stand-in for it lives here once.
"""

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk.capture import drain_log_capture
from zamp_sdk.context.constants import ZAMP_METADATA_CONTEXT_KEY
from zamp_sdk.logging import log_control

ACTION_EXECUTOR_EXECUTE_PATH = "zamp_sdk.action_executor.ActionExecutor.execute"


@pytest.fixture(autouse=True)
def reset_logging_state(monkeypatch):
    log_control._config.set(None)
    for name in ("ZAMP_LOG_LEVEL", "ZAMP_LOG_ENABLED", "ZAMP_AUTO_ACTION_LOGS"):
        monkeypatch.delenv(name, raising=False)
    # Capture is a context variable too: a test that starts it and doesn't drain must not leak steps into the next.
    drain_log_capture()
    yield
    drain_log_capture()


@pytest.fixture
def bind_metadata_context():
    def bind(metadata):
        bound = {ZAMP_METADATA_CONTEXT_KEY: metadata}
        context_utils = SimpleNamespace(get_variable_from_context=bound.get)
        return patch.dict(sys.modules, {"zamp_public_workflow_sdk.actions_hub.utils.context_utils": context_utils})

    return bind


def drained_steps() -> list[dict]:
    """Drain the step buffer and parse each JSON line back into the step it recorded."""
    return [json.loads(line) for line in drain_log_capture()]


@pytest.fixture(autouse=True)
def _outside_any_eval_trial(monkeypatch):
    monkeypatch.delenv("ZAMP_SDK_EXECUTION_HOST", raising=False)
    monkeypatch.delenv("ZAMP_EVAL_TRIAL_ID", raising=False)


@pytest.fixture
def in_eval_trial(monkeypatch):
    monkeypatch.setenv("ZAMP_EVAL_TRIAL_ID", "run1-1-item1-1")


@pytest.fixture
def in_eval_trial_on_actions_hub(monkeypatch, bind_metadata_context):
    with _on_actions_hub(monkeypatch, bind_metadata_context({"eval_trial_id": "run1-1-item1-1"})):
        yield


@pytest.fixture
def on_actions_hub_outside_a_trial(monkeypatch, bind_metadata_context):
    with _on_actions_hub(monkeypatch, bind_metadata_context({"branch_id": "b1"})):
        yield


@contextmanager
def _on_actions_hub(monkeypatch, bound_metadata_context):
    monkeypatch.setenv("ZAMP_SDK_EXECUTION_HOST", "actions_hub")
    temporalio = SimpleNamespace(workflow=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="workflow-uuid")))
    with bound_metadata_context, patch.dict(sys.modules, {"temporalio": temporalio}):
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
def mock_failed():
    return lambda message: {"kind": "mock_failed", "code": "MOCK_FAILED", "message": message}
