"""Per-test isolation for the logging state.

Both switches live in context variables that outlive a single test in the same task, so without
this one test's `configure_logging` silently changes what the next one asserts. At the root
rather than per package: the state is shared, so resetting it should be too. The environment
variable is cleared for the same reason.
"""

import pytest

from zamp_sdk.logging import log_control


@pytest.fixture(autouse=True)
def reset_logging_state(monkeypatch):
    log_control._config.set(None)
    for name in ("ZAMP_LOG_LEVEL", "ZAMP_LOG_ENABLED", "ZAMP_AUTO_ACTION_LOGS"):
        monkeypatch.delenv(name, raising=False)
