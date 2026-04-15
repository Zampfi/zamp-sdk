from unittest.mock import MagicMock, patch

import pytest

from zamp_sdk.action_executor.execution_mode import (
    ExecutionMode,
    resolve_ah_execution_mode,
)


class TestExecutionMode:
    def test_enum_members(self):
        assert ExecutionMode.SYNC.value == "SYNC"
        assert ExecutionMode.ASYNC.value == "ASYNC"
        assert ExecutionMode.INLINE.value == "INLINE"

    def test_is_str_enum(self):
        assert ExecutionMode.SYNC == "SYNC"


class TestResolveAhExecutionMode:
    def test_returns_none_when_mode_is_none(self):
        assert resolve_ah_execution_mode(None) is None

    def test_maps_sync_to_temporal_sync(self):
        fake_mode = MagicMock()
        fake_mode.TEMPORAL_SYNC = "TEMPORAL_SYNC_SENTINEL"
        fake_mode.TEMPORAL_ASYNC = "TEMPORAL_ASYNC_SENTINEL"
        fake_mode.INLINE = "INLINE_SENTINEL"

        with patch.dict(
            "sys.modules",
            {
                "zamp_public_workflow_sdk": MagicMock(),
                "zamp_public_workflow_sdk.actions_hub": MagicMock(),
                "zamp_public_workflow_sdk.actions_hub.constants": MagicMock(
                    ExecutionMode=fake_mode,
                ),
            },
        ):
            assert resolve_ah_execution_mode(ExecutionMode.SYNC) == "TEMPORAL_SYNC_SENTINEL"
            assert resolve_ah_execution_mode(ExecutionMode.ASYNC) == "TEMPORAL_ASYNC_SENTINEL"
            assert resolve_ah_execution_mode(ExecutionMode.INLINE) == "INLINE_SENTINEL"

    def test_raises_import_error_when_dependency_missing(self):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("zamp_public_workflow_sdk"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="zamp_public_workflow_sdk"):
                resolve_ah_execution_mode(ExecutionMode.SYNC)
