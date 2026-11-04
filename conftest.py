"""Fixtures shared by every package's tests.

Logging state: both switches live in context variables that outlive a single test in the same task,
so without a reset one test's `configure_logging` silently changes what the next one asserts. At the
root rather than per package: the state is shared, so resetting it should be too. The environment
variable is cleared for the same reason.

Metadata context: on the actions hub the executor binds a dict that `zamp_sdk.context` and
`zamp_sdk.evals` both read, so the stand-in for it lives here once.
"""

import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from zamp_sdk.capture import drain_log_capture
from zamp_sdk.context.constants import ZAMP_METADATA_CONTEXT_KEY
from zamp_sdk.logging import log_control


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
