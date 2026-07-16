"""SDK version reporting.

Covers the single-source-of-truth version and that it rides on every SDK log
line — including the progress logs emitted *before* ``emit_log`` reaches the
platform.
"""

from importlib.metadata import version
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

import zamp_sdk
from zamp_sdk import emit_text
from zamp_sdk.logger import get_logger
from zamp_sdk.version import __version__


class TestSdkVersion:
    def test_matches_package_metadata(self):
        assert __version__ == version("zamp-sdk")

    def test_exposed_at_package_root(self):
        assert zamp_sdk.__version__ == __version__

    def test_is_nonempty_string(self):
        assert isinstance(__version__, str)
        assert __version__


class TestLoggerBindsVersion:
    def test_get_logger_binds_sdk_version(self):
        logger = get_logger("test.logger")
        with capture_logs() as logs:
            logger.info("hello", foo="bar")

        assert len(logs) == 1
        assert logs[0]["sdk_version"] == __version__
        assert logs[0]["event"] == "hello"
        assert logs[0]["foo"] == "bar"


class TestPreEmitLogsCarryVersion:
    @pytest.mark.asyncio
    async def test_emit_text_progress_log_has_version(self):
        # emit_text logs "emit_text" *before* the emit_log action fires — that
        # early log line must still carry the SDK version.
        execute = AsyncMock(return_value={"ok": True})
        with capture_logs() as logs:
            with patch("zamp_sdk.logging.logging.ActionExecutor.execute", execute):
                await emit_text("step done")

        progress = [entry for entry in logs if entry.get("event") == "emit_text"]
        assert progress, "expected a pre-emit progress log"
        assert progress[0]["sdk_version"] == __version__
