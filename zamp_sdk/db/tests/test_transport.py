"""Which transport each dataset call uses.

Reads and writes run inline — one round trip, no poll — because they are short and
time-sensitive. DDL stays on the durable path.
"""

from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from zamp_sdk.action_executor import ExecutionMode
from zamp_sdk.db import datasets

_EXECUTE = "zamp_sdk.db.utils.actions.ActionExecutor.execute"

_DESCRIBE_RESPONSE = {
    "datasets": [
        {
            "table_name": "invoices",
            "primary_key": ["id"],
            "columns": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "vendor", "type": "text", "nullable": True},
            ],
        }
    ]
}


@pytest.fixture
def executor():
    with patch(_EXECUTE, new=AsyncMock()) as mock:
        mock.return_value = _DESCRIBE_RESPONSE
        yield mock


def _modes(executor) -> list:
    return [call.kwargs.get("execution_mode") for call in executor.await_args_list]


class TestInlineCalls:
    @pytest.mark.asyncio
    async def test_describe_runs_inline(self, executor):
        await datasets.tables(["invoices"])

        assert _modes(executor) == [ExecutionMode.INLINE]

    @pytest.mark.asyncio
    async def test_execute_runs_inline(self, executor):
        table = await datasets.table("invoices")
        executor.return_value = {"results": [{"rows": [], "row_count": 0}]}

        await datasets.execute(select(table))

        assert _modes(executor)[-1] is ExecutionMode.INLINE

    @pytest.mark.asyncio
    async def test_transaction_runs_inline(self, executor):
        table = await datasets.table("invoices")
        executor.return_value = {"results": [{"rows": [], "row_count": 1}]}

        async with datasets.transaction() as tx:
            tx.add(sa.insert(table).values(vendor="Acme"))

        assert _modes(executor)[-1] is ExecutionMode.INLINE

    @pytest.mark.asyncio
    async def test_inline_calls_still_send_no_retry_or_timeout_override(self, executor):
        table = await datasets.table("invoices")
        executor.return_value = {"results": [{"rows": [], "row_count": 0}]}

        await datasets.execute(select(table))

        assert "action_retry_policy" not in executor.await_args.kwargs
        assert "action_start_to_close_timeout" not in executor.await_args.kwargs


class TestDurableCalls:
    @pytest.mark.asyncio
    async def test_create_stays_on_the_durable_path(self, executor):
        table = sa.Table("invoices", sa.MetaData(), sa.Column("vendor", sa.Text))

        await datasets.create(table)

        create_call, describe_call = executor.await_args_list
        assert create_call.kwargs.get("execution_mode") is None
        assert describe_call.kwargs.get("execution_mode") is ExecutionMode.INLINE

    @pytest.mark.asyncio
    async def test_drop_stays_on_the_durable_path(self, executor):
        await datasets.drop("invoices")

        assert _modes(executor) == [None]
