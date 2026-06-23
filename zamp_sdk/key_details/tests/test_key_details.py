from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    get_dataset_key_details,
    reconcile_dataset_change,
    record_task_key_detail_rows,
    upsert_dataset_key_details,
)
from zamp_sdk.key_details.key_details import _resolve_task_id

EXECUTE = "zamp_sdk.key_details.key_details.ActionExecutor.execute"


@pytest.fixture(autouse=True)
def _clear_zamp_env(monkeypatch):
    for var in ("ZAMP_CHANNEL_TYPE", "ZAMP_CHANNEL_ID"):
        monkeypatch.delenv(var, raising=False)


class TestResolveTaskId:
    def test_returns_channel_id_in_task_context(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-1")
        assert _resolve_task_id() == "task-1"

    def test_none_in_conversation_context(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-1")
        assert _resolve_task_id() is None

    def test_none_when_no_context(self):
        assert _resolve_task_id() is None

    def test_none_when_task_type_but_no_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        assert _resolve_task_id() is None


class TestRecordTaskKeyDetailRows:
    @pytest.mark.asyncio
    async def test_records_against_channel_task_id(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-7")
        execute = AsyncMock(return_value={"task_id": "task-7", "row_count": 3})
        with patch(EXECUTE, execute):
            result = await record_task_key_detail_rows("invoices", [1, 2, 3])

        action_name, params = execute.call_args.args
        assert action_name == "update_task_key_detail_rows"
        assert params["task_id"] == "task-7"
        assert params["rows"] == [{"table": "invoices", "row_ids": [1, 2, 3]}]
        assert result == {"task_id": "task-7", "row_count": 3}

    @pytest.mark.asyncio
    async def test_noop_outside_task_context(self, monkeypatch):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "conv-1")
        execute = AsyncMock()
        with patch(EXECUTE, execute):
            result = await record_task_key_detail_rows("invoices", [1])

        execute.assert_not_called()
        assert result == {"recorded": False}


class TestConfigHelpers:
    @pytest.mark.asyncio
    async def test_get_dataset_key_details(self):
        execute = AsyncMock(return_value={"registered": False, "columns": []})
        with patch(EXECUTE, execute):
            await get_dataset_key_details("invoices")
        action_name, params = execute.call_args.args
        assert action_name == "get_dataset_key_details"
        assert params == {"table_name": "invoices"}

    @pytest.mark.asyncio
    async def test_upsert_dataset_key_details(self):
        cols = [{"label": "Invoice #", "column": "invoice_number"}]
        execute = AsyncMock(return_value={"columns": cols})
        with patch(EXECUTE, execute):
            await upsert_dataset_key_details("invoices", cols)
        action_name, params = execute.call_args.args
        assert action_name == "upsert_dataset_key_details"
        assert params == {"table_name": "invoices", "columns": cols}

    @pytest.mark.asyncio
    async def test_reconcile_rename_carries_new_name(self):
        execute = AsyncMock(return_value={"rows_affected": 1})
        with patch(EXECUTE, execute):
            await reconcile_dataset_change("RENAME", "old_t", "new_t")
        _, params = execute.call_args.args
        assert params == {
            "action": "RENAME",
            "old_table_name": "old_t",
            "new_table_name": "new_t",
        }

    @pytest.mark.asyncio
    async def test_reconcile_drop_omits_new_name(self):
        execute = AsyncMock(return_value={"rows_affected": 1})
        with patch(EXECUTE, execute):
            await reconcile_dataset_change("DROP", "old_t")
        _, params = execute.call_args.args
        assert params == {"action": "DROP", "old_table_name": "old_t"}
        assert "new_table_name" not in params
