"""Fixtures shared by every package's tests.

Logging state: both switches live in context variables that outlive a single test in the same task,
so without a reset one test's `configure_logging` silently changes what the next one asserts. At the
root rather than per package: the state is shared, so resetting it should be too. The environment
variable is cleared for the same reason.

Metadata context: on the actions hub the executor binds a dict that `zamp_sdk.context` and
`zamp_sdk.evals` both read, so the stand-in for it lives here once.
"""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from zamp_sdk.context.constants import ZAMP_METADATA_CONTEXT_KEY
from zamp_sdk.logging import emit_budget, log_control
from zamp_sdk.logging.constants import DEFAULT_MAX_EMITS


@pytest.fixture(autouse=True)
def reset_logging_state(monkeypatch):
    log_control._config.set(None)
    for name in ("ZAMP_LOG_LEVEL", "ZAMP_LOG_ENABLED", "ZAMP_AUTO_ACTION_LOGS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def reset_emit_budget():
    """The emit budget is process-wide on the API host, so its count would leak between tests."""
    emit_budget._budget.set(None)
    emit_budget._PROCESS_BUDGET.limit = DEFAULT_MAX_EMITS
    emit_budget._PROCESS_BUDGET.sent = 0
    emit_budget._PROCESS_BUDGET.stopped = False
    emit_budget._PROCESS_BUDGET.warned = False


@pytest.fixture
def bind_metadata_context():
    def bind(metadata):
        bound = {ZAMP_METADATA_CONTEXT_KEY: metadata}
        context_utils = SimpleNamespace(get_variable_from_context=bound.get)
        return patch.dict(sys.modules, {"zamp_public_workflow_sdk.actions_hub.utils.context_utils": context_utils})

    return bind
