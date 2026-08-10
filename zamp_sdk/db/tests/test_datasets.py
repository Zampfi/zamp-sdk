"""The six-call façade, with the platform stubbed out.

Nothing here touches a network or a database. The assertions are about the payload
that would go over the wire, because that payload *is* the contract with Pantheon.
"""

from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import insert, select, update

from zamp_sdk.db import datasets
from zamp_sdk.db.errors import AgentDbError

_ACTIONS = "zamp_sdk.db._actions.ActionExecutor.execute"

DESCRIBE_RESPONSE = {
    "datasets": [
        {
            "table_name": "invoices",
            "primary_key": ["id"],
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "default": "nextval('invoices_id_seq'::regclass)"},
                {"name": "vendor", "type": "text", "nullable": True},
                {"name": "amount", "type": "numeric", "precision": 12, "scale": 2, "nullable": True},
            ],
        }
    ]
}


@pytest.fixture
def executor():
    with patch(_ACTIONS, new=AsyncMock()) as mock:
        mock.return_value = {"results": [{"rows": [], "row_count": 0}]}
        yield mock


async def _invoices(executor):
    executor.return_value = DESCRIBE_RESPONSE
    table = await datasets.table("invoices")
    executor.reset_mock()
    executor.return_value = {"results": [{"rows": [], "row_count": 0}]}
    return table


class TestDescribe:
    @pytest.mark.asyncio
    async def test_table_builds_a_usable_table(self, executor):
        executor.return_value = DESCRIBE_RESPONSE

        table = await datasets.table("invoices")

        assert isinstance(table, sa.Table)
        assert set(table.c.keys()) == {"id", "vendor", "amount"}

    @pytest.mark.asyncio
    async def test_tables_batches_into_one_call(self, executor):
        """Nine tables should cost one describe, not nine."""
        executor.return_value = DESCRIBE_RESPONSE

        await datasets.tables(["invoices", "orders", "vendors"])

        assert executor.await_count == 1
        assert executor.await_args.args[1]["table_names"] == ["invoices", "orders", "vendors"]

    @pytest.mark.asyncio
    async def test_batched_tables_share_one_metadata_so_joins_compose(self, executor):
        executor.return_value = {
            "datasets": [
                DESCRIBE_RESPONSE["datasets"][0],
                {
                    "table_name": "vendors",
                    "primary_key": ["id"],
                    "columns": [{"name": "id", "type": "integer", "nullable": False}],
                },
            ]
        }

        built = await datasets.tables(["invoices", "vendors"])

        assert built["invoices"].metadata is built["vendors"].metadata

    @pytest.mark.asyncio
    async def test_a_missing_dataset_is_a_clear_error(self, executor):
        """An empty describe means "no such table, or no access" — the platform
        privilege-filters, so the two are indistinguishable and both are errors."""
        executor.return_value = {"datasets": []}

        with pytest.raises(AgentDbError) as exc:
            await datasets.table("nope")

        assert "nope" in str(exc.value)


class TestExecute:
    @pytest.mark.asyncio
    async def test_compiles_to_sql_plus_bound_params(self, executor):
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.vendor == "Acme"))

        payload = executor.await_args.args[1]
        statement = payload["statements"][0]
        assert "SELECT" in statement["sql"]
        assert "%(vendor_1)s" in statement["sql"]
        assert statement["params"] == {"vendor_1": "Acme"}

    @pytest.mark.asyncio
    async def test_values_are_never_inlined(self, executor):
        """literal_binds would put the value in the SQL text, losing type fidelity
        and requiring us to reimplement Postgres escaping."""
        table = await _invoices(executor)

        await datasets.execute(insert(table).values(vendor="O'Brien"))

        statement = executor.await_args.args[1]["statements"][0]
        assert "O'Brien" not in statement["sql"]
        assert "O'Brien" in statement["params"].values()

    @pytest.mark.asyncio
    async def test_in_lists_expand_to_one_bind_each(self, executor):
        """Without render_postcompile the SQL carries one token standing for the
        whole list, which no driver can bind."""
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.vendor.in_(["a", "b", "c"])))

        statement = executor.await_args.args[1]["statements"][0]
        assert len(statement["params"]) == 3

    @pytest.mark.asyncio
    async def test_returns_the_first_statements_rows(self, executor):
        table = await _invoices(executor)
        executor.return_value = {"results": [{"rows": [{"id": 1}], "row_count": 1}]}

        rows = await datasets.execute(select(table))

        assert rows == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_expected_rows_is_forwarded(self, executor):
        table = await _invoices(executor)

        await datasets.execute(update(table).where(table.c.id == 1).values(vendor="x"), expected_rows=1)

        assert executor.await_args.args[1]["statements"][0]["expected_rows"] == 1

    @pytest.mark.asyncio
    async def test_never_sends_retry_timeout_or_idempotency_overrides(self, executor):
        """The platform's defaults exist because someone reasoned about the seam. A
        client-side override would silently replace that reasoning — and would add a
        write retry the raw psycopg2 path never had."""
        table = await _invoices(executor)

        await datasets.execute(select(table))

        assert "action_retry_policy" not in executor.await_args.kwargs
        assert "action_start_to_close_timeout" not in executor.await_args.kwargs
        assert "idempotency_key" not in executor.await_args.args[1]


class TestTransaction:
    @pytest.mark.asyncio
    async def test_one_call_carries_every_statement(self, executor):
        table = await _invoices(executor)

        async with datasets.transaction() as tx:
            tx.add(insert(table).values(vendor="a"))
            tx.add(insert(table).values(vendor="b"))
            tx.add(update(table).where(table.c.id == 1).values(vendor="c"))

        assert executor.await_count == 1
        assert len(executor.await_args.args[1]["statements"]) == 3

    @pytest.mark.asyncio
    async def test_results_align_with_add_order(self, executor):
        table = await _invoices(executor)
        executor.return_value = {"results": [{"rows": [{"n": 1}]}, {"rows": [{"n": 2}]}]}

        async with datasets.transaction() as tx:
            first = tx.add(select(table))
            second = tx.add(select(table))

        assert (first, second) == (0, 1)
        assert tx.results[first]["rows"] == [{"n": 1}]
        assert tx.results[second]["rows"] == [{"n": 2}]

    @pytest.mark.asyncio
    async def test_an_exception_inside_the_block_sends_nothing(self, executor):
        """The caller never finished describing the unit of work, so shipping a
        half-built body would commit an intent nobody stated."""
        table = await _invoices(executor)

        with pytest.raises(ValueError):
            async with datasets.transaction() as tx:
                tx.add(insert(table).values(vendor="a"))
                raise ValueError("author changed their mind")

        executor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_empty_block_sends_nothing(self, executor):
        async with datasets.transaction():
            pass

        executor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expected_rows_rides_per_statement(self, executor):
        table = await _invoices(executor)

        async with datasets.transaction() as tx:
            tx.add(insert(table).values(vendor="a"))
            tx.add(update(table).values(vendor="b"), expected_rows=1)

        statements = executor.await_args.args[1]["statements"]
        assert "expected_rows" not in statements[0]
        assert statements[1]["expected_rows"] == 1


class TestStream:
    @pytest.mark.asyncio
    async def test_pages_with_a_keyset_cursor_and_stops_on_a_short_page(self, executor):
        table = await _invoices(executor)
        executor.side_effect = [
            {"results": [{"rows": [{"id": 1}, {"id": 2}]}]},
            {"results": [{"rows": [{"id": 3}, {"id": 4}]}]},
            {"results": [{"rows": [{"id": 5}]}]},
        ]

        pages = [page async for page in datasets.stream(select(table), page_size=2)]

        assert [len(p) for p in pages] == [2, 2, 1]
        assert executor.await_count == 3

    @pytest.mark.asyncio
    async def test_the_cursor_advances_past_the_last_row_seen(self, executor):
        table = await _invoices(executor)
        executor.side_effect = [
            {"results": [{"rows": [{"id": 1}, {"id": 7}]}]},
            {"results": [{"rows": []}]},
        ]

        [page async for page in datasets.stream(select(table), page_size=2)]

        second_call_sql = executor.await_args_list[1].args[1]["statements"][0]
        assert 7 in second_call_sql["params"].values()

    @pytest.mark.asyncio
    async def test_page_size_caps_the_servers_row_limit_too(self, executor):
        """Each page is one call, so page_size may not exceed max_result_rows —
        sending it explicitly keeps the two from drifting apart."""
        table = await _invoices(executor)
        executor.side_effect = [{"results": [{"rows": []}]}]

        [page async for page in datasets.stream(select(table), page_size=500)]

        assert executor.await_args.args[1]["max_result_rows"] == 500

    @pytest.mark.asyncio
    async def test_a_missing_key_column_says_so_clearly(self, executor):
        no_id = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text))

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(no_id))]

        assert "key=" in str(exc.value)


class TestCreateAndDrop:
    @pytest.mark.asyncio
    async def test_create_compiles_ddl_and_mirrors_the_id_column(self, executor):
        source = sa.Table("customers", sa.MetaData(), sa.Column("name", sa.Text, nullable=False))

        mirrored = await datasets.create(source, if_exists="skip")

        payload = executor.await_args.args[1]
        assert payload["create_sql"].startswith("CREATE TABLE customers")
        assert payload["if_exists"] == "skip"
        # The returned Table is the one to build expressions from.
        assert "id" in mirrored.c

    @pytest.mark.asyncio
    async def test_create_defaults_to_error(self, executor):
        source = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text))

        await datasets.create(source)

        assert executor.await_args.args[1]["if_exists"] == "error"

    @pytest.mark.asyncio
    async def test_drop_accepts_a_table_or_a_name(self, executor):
        source = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text))

        await datasets.drop(source)
        assert executor.await_args.args[1]["table_name"] == "t"

        await datasets.drop("other")
        assert executor.await_args.args[1]["table_name"] == "other"
