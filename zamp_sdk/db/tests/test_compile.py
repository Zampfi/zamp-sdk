"""What ``compile_statement`` puts on the wire.

The compile step had no tests of its own, which is how a ``dict`` bound to a jsonb
column shipped as a defect: every other test asserted on the *shape* of the outgoing
payload, and none on the values inside it. These assert the values.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from zamp_sdk.db.utils.compile import compile_statement


@pytest.fixture
def invoices() -> sa.Table:
    return sa.Table(
        "invoices",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vendor", sa.String),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("meta", JSONB),
        sa.Column("tags", ARRAY(sa.Text)),
        sa.Column("seen", sa.DateTime(timezone=True)),
        sa.Column("ref", sa.Uuid),
    )


class TestPlaceholders:
    """SQLAlchemy emits them; nothing here rewrites SQL."""

    def test_placeholders_are_dollar_n_not_pyformat(self, invoices):
        sql, args = compile_statement(sa.select(invoices.c.id).where(invoices.c.vendor == "Acme"))
        assert "$1" in sql
        assert "%(" not in sql
        assert args == ["Acme"]

    def test_arguments_are_positional_and_in_placeholder_order(self, invoices):
        sql, args = compile_statement(
            sa.select(invoices.c.id).where(invoices.c.vendor == "Acme").where(invoices.c.amount > 100)
        )
        assert sql.index("$1") < sql.index("$2")
        assert args == ["Acme", 100]

    def test_a_value_used_twice_is_sent_once(self, invoices):
        """A repeated bind is one Postgres parameter, so it takes one argument.

        The compiler decides this. Getting it wrong in either direction is an arity
        error at prepare time, not a wrong answer, but it used to be our arithmetic.
        """
        target = sa.bindparam("target", "Acme")
        sql, args = compile_statement(
            sa.select(invoices.c.id).where(sa.or_(invoices.c.vendor == target, invoices.c.tags.any(target)))
        )
        assert args == ["Acme"]
        assert sql.count("$1") == 2
        assert "$2" not in sql

    def test_in_lists_expand_to_one_placeholder_per_element(self, invoices):
        """Without render_postcompile the SQL carries one token for the whole list,
        which no driver can bind."""
        sql, args = compile_statement(sa.select(invoices.c.id).where(invoices.c.vendor.in_(["a", "b", "c"])))
        assert "POSTCOMPILE" not in sql
        assert args == ["a", "b", "c"]
        assert "$3" in sql

    def test_a_literal_percent_is_never_doubled(self, invoices):
        """The %% escaping only exists for pyformat. Under $n there is nothing to
        escape, so a LIKE pattern survives as written."""
        sql, args = compile_statement(sa.select(invoices.c.id).where(invoices.c.vendor.like("%100%")))
        assert "%%" not in sql
        assert args == ["%100%"]

    def test_ddl_carries_no_arguments(self, invoices):
        """DDL compiles to a PGDDLCompiler, which has neither positiontup nor params."""
        sql, args = compile_statement(sa.schema.CreateTable(invoices))
        assert sql.startswith("\nCREATE TABLE invoices") or "CREATE TABLE" in sql
        assert args == []


class TestValues:
    """The half that had no coverage, and where the jsonb defect lived."""

    def test_a_dict_bound_to_jsonb_is_serialised(self, invoices):
        """Regression. asyncpg cannot encode a dict — the value has to arrive as the
        JSON text SQLAlchemy's own bind processor produces. Reading compiled.params
        without running the processors sends the raw dict and fails at execute time
        with "'dict' object has no attribute 'encode'"."""
        _, args = compile_statement(pg_insert(invoices).values(meta={"po": 42}))
        assert args == ['{"po": 42}']
        assert isinstance(args[0], str)

    def test_a_list_bound_to_an_array_column_stays_a_list(self, invoices):
        _, args = compile_statement(pg_insert(invoices).values(tags=["a", "b"]))
        assert args == [["a", "b"]]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("10.25"), "10.25"),
            (dt.datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05"),
            (dt.date(2026, 1, 2), "2026-01-02"),
            (dt.time(3, 4, 5), "03:04:05"),
            (uuid.UUID("11111111-1111-1111-1111-111111111111"), "11111111-1111-1111-1111-111111111111"),
            (b"\x00\x01\xff", "\\x0001ff"),
        ],
    )
    def test_scalars_json_cannot_carry_travel_as_text(self, value, expected):
        """Each is the text form Postgres's own input function parses. The
        placeholder already names the type, so nothing is inferred server-side."""
        _, args = compile_statement(sa.select(sa.literal(value)))
        assert args == [expected]

    def test_the_whole_payload_survives_json(self, invoices):
        """The wire is JSON. A value that cannot round-trip through it is a bug that
        surfaces as a serialisation error inside the SDK's HTTP layer, far from here."""
        sql, args = compile_statement(
            pg_insert(invoices).values(
                vendor="Acme 100%",
                amount=Decimal("10.25"),
                meta={"po": 42},
                tags=["x"],
                seen=dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc),
                ref=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            )
        )
        assert json.loads(json.dumps({"sql": sql, "args": args}))["args"] == args

    def test_none_is_passed_through(self, invoices):
        _, args = compile_statement(sa.select(invoices.c.id).where(invoices.c.vendor == sa.null()))
        assert args == []


class TestNothingIsInlined:
    def test_values_never_appear_in_the_sql_text(self, invoices):
        """literal_binds would lose type fidelity and require reimplementing Postgres
        escaping. Values stay arguments — including a string that looks like SQL."""
        sql, args = compile_statement(sa.select(invoices.c.id).where(invoices.c.vendor == "'; DROP TABLE t --"))
        assert "DROP TABLE" not in sql
        assert args == ["'; DROP TABLE t --"]
