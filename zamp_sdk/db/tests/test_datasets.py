"""The six-call façade, with the platform stubbed out.

Nothing here touches a network or a database. The assertions are about the payload
that would go over the wire, because that payload *is* the contract with Pantheon.
"""

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
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
                {"name": "created_at", "type": "timestamp without time zone", "nullable": True},
                {"name": "doc", "type": "bytea", "nullable": True},
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
        assert set(table.c.keys()) == {"id", "vendor", "amount", "created_at", "doc"}

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
    async def test_compiles_to_sql_plus_positional_args(self, executor):
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.vendor == "Acme"))

        payload = executor.await_args.args[1]
        statement = payload["statements"][0]
        assert "SELECT" in statement["sql"]
        assert "$1" in statement["sql"]
        assert "%(" not in statement["sql"]
        assert statement["args"] == ["Acme"]

    @pytest.mark.asyncio
    async def test_values_are_never_inlined(self, executor):
        """literal_binds would put the value in the SQL text, losing type fidelity
        and requiring us to reimplement Postgres escaping."""
        table = await _invoices(executor)

        await datasets.execute(insert(table).values(vendor="O'Brien"))

        statement = executor.await_args.args[1]["statements"][0]
        assert "O'Brien" not in statement["sql"]
        assert "O'Brien" in statement["args"]

    @pytest.mark.asyncio
    async def test_in_lists_expand_to_one_bind_each(self, executor):
        """Without render_postcompile the SQL carries one token standing for the
        whole list, which no driver can bind."""
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.vendor.in_(["a", "b", "c"])))

        statement = executor.await_args.args[1]["statements"][0]
        assert len(statement["args"]) == 3

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
    async def test_a_timestamp_crosses_the_wire_as_json(self, executor):
        """The payload is serialised with plain json.dumps, which cannot encode a
        datetime — so the value travels as text. The placeholder already names the
        type, because the dialect printed the cast itself."""
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.created_at > datetime(2026, 1, 1)))

        payload = executor.await_args.args[1]
        statement = payload["statements"][0]
        json.dumps(payload)
        assert statement["args"] == ["2026-01-01T00:00:00"]
        assert "$1::TIMESTAMP" in statement["sql"]

    @pytest.mark.asyncio
    async def test_an_aware_timestamp_keeps_its_zone(self, executor):
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.created_at > datetime(2026, 1, 1, tzinfo=timezone.utc)))

        statement = executor.await_args.args[1]["statements"][0]
        assert statement["args"] == ["2026-01-01T00:00:00+00:00"]

    @pytest.mark.asyncio
    async def test_dates_decimals_and_uuids_all_survive_serialisation(self, executor):
        """The shipped reference template declares a Numeric column, so this is the
        first value shape an author is likely to bind."""
        table = await _invoices(executor)
        identifier = uuid.UUID("6b1f8e2c-6f5a-4f9a-9a3e-2f5f4d2b7c11")

        async with datasets.transaction() as tx:
            tx.add(insert(table).values(vendor="a", amount=Decimal("12.50")))
            tx.add(select(table).where(table.c.created_at > date(2026, 1, 1)))
            tx.add(select(table).where(table.c.vendor == identifier))

        payload = executor.await_args.args[1]
        json.dumps(payload)
        sent = [statement["args"] for statement in payload["statements"]]
        assert "12.50" in sent[0]
        assert sent[1] == ["2026-01-01"]
        assert sent[2] == [str(identifier)]

    @pytest.mark.asyncio
    async def test_bytes_travel_as_hex(self, executor):
        table = await _invoices(executor)

        await datasets.execute(select(table).where(table.c.doc == b"\x00\xff"))

        statement = executor.await_args.args[1]["statements"][0]
        json.dumps(statement)
        assert statement["args"] == ["\\x00ff"]

    @pytest.mark.asyncio
    async def test_every_element_of_an_in_list_is_encoded(self, executor):
        """render_postcompile gives each element its own placeholder, so the encoding
        has to reach every expanded position rather than the original one."""
        table = await _invoices(executor)

        await datasets.execute(
            select(table).where(table.c.created_at.in_([datetime(2026, 1, 1), datetime(2026, 2, 1)]))
        )

        statement = executor.await_args.args[1]["statements"][0]
        json.dumps(statement)
        assert statement["args"] == ["2026-01-01T00:00:00", "2026-02-01T00:00:00"]

    @pytest.mark.asyncio
    async def test_a_literal_percent_is_never_escaped(self, executor):
        """Under $n there is no percent escaping at all — the %% doubling only ever
        existed because pyformat needed it, and both halves of undoing it are gone."""
        await _invoices(executor)

        await datasets.execute(sa.text("UPDATE invoices SET vendor = 'paid 100%' WHERE id = 1"))

        statement = executor.await_args.args[1]["statements"][0]
        assert statement["sql"] == "UPDATE invoices SET vendor = 'paid 100%' WHERE id = 1"
        assert "args" not in statement

    @pytest.mark.asyncio
    async def test_never_sends_retry_or_timeout_overrides(self, executor):
        """The platform's defaults exist because someone reasoned about the seam. A
        client-side override would silently replace that reasoning — and would add a
        write retry the raw psycopg2 path never had."""
        table = await _invoices(executor)

        await datasets.execute(select(table))

        assert "action_retry_policy" not in executor.await_args.kwargs
        assert "action_start_to_close_timeout" not in executor.await_args.kwargs


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
        assert 7 in second_call_sql["args"]

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

    @pytest.mark.asyncio
    async def test_a_key_the_projection_omits_is_refused_before_the_first_call(self, executor):
        """The key is read back out of the returned rows, so resolving it against the
        source table would page on a value that never arrives — a KeyError on page
        two, and only once the first page is full enough to reach it."""
        table = await _invoices(executor)

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(table.c.vendor), page_size=2)]

        assert "key=" in str(exc.value)
        executor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_nullable_key_column_is_refused(self, executor):
        """A UNIQUE column may still hold several NULLs, and NULLs sort last, so the
        cursor either stops advancing on them or filters them away."""
        table = await _invoices(executor)

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(table), key="vendor")]

        assert "nullable" in str(exc.value)
        executor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_null_cursor_stops_instead_of_refetching_the_same_page(self, executor):
        """`key > NULL` is NULL and matches nothing, so the where-clause would be
        dropped and the identical full page fetched again, forever."""
        table = await _invoices(executor)
        executor.side_effect = [{"results": [{"rows": [{"id": 1}, {"id": None}]}]}]

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(table), page_size=2)]

        assert "NULL" in str(exc.value)
        assert executor.await_count == 1

    @pytest.mark.asyncio
    async def test_an_order_by_on_the_statement_is_refused(self, executor):
        """order_by() appends, so the caller's key would lead and the cursor would
        page against a different order — silently skipping and repeating rows."""
        table = await _invoices(executor)

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(table).order_by(table.c.vendor))]

        assert "order_by()" in str(exc.value)
        executor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_limit_on_the_statement_is_refused(self, executor):
        """limit() replaces, so the caller's bound would be thrown away and the whole
        table read a page at a time."""
        table = await _invoices(executor)

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(table).limit(2), page_size=3)]

        assert "limit()" in str(exc.value)
        executor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_offset_on_the_statement_is_refused(self, executor):
        """offset() is neither replaced nor reset, so it would be re-applied past the
        cursor on every page and drop rows out of the middle of the stream."""
        table = await _invoices(executor)

        with pytest.raises(AgentDbError) as exc:
            [page async for page in datasets.stream(select(table).offset(100))]

        assert "offset()" in str(exc.value)
        executor.assert_not_awaited()


class TestCreateAndDrop:
    _CUSTOMERS_DESCRIBE = {
        "datasets": [
            {
                "table_name": "customers",
                "primary_key": ["id"],
                "columns": [
                    {
                        "name": "id",
                        "type": "integer",
                        "nullable": False,
                        "default": "nextval('customers_id_seq'::regclass)",
                    },
                    {"name": "name", "type": "text", "nullable": False},
                ],
            }
        ]
    }

    @pytest.mark.asyncio
    async def test_create_sends_the_authors_ddl_and_returns_the_described_table(self, executor):
        executor.return_value = self._CUSTOMERS_DESCRIBE
        source = sa.Table("customers", sa.MetaData(), sa.Column("name", sa.Text, nullable=False))

        result = await datasets.create(source, if_exists="skip")

        # First call is the create: the author's DDL as-is, no client-side id injection.
        create_payload = executor.await_args_list[0].args[1]
        assert create_payload["create_sql"].startswith("CREATE TABLE customers")
        assert '"id"' not in create_payload["create_sql"]
        assert create_payload["if_exists"] == "skip"
        # Then it re-describes, and the returned Table is the server's — with the id.
        assert len(executor.await_args_list) == 2
        assert "id" in result.c and "name" in result.c
        assert result.name == "customers"

    @pytest.mark.asyncio
    async def test_create_defaults_to_error(self, executor):
        executor.return_value = self._CUSTOMERS_DESCRIBE
        source = sa.Table("customers", sa.MetaData(), sa.Column("name", sa.Text))

        await datasets.create(source)

        assert executor.await_args_list[0].args[1]["if_exists"] == "error"

    @pytest.mark.asyncio
    async def test_drop_accepts_a_table_or_a_name(self, executor):
        source = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text))

        await datasets.drop(source)
        assert executor.await_args.args[1]["table_name"] == "t"

        await datasets.drop("other")
        assert executor.await_args.args[1]["table_name"] == "other"
