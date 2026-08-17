"""Turning the platform's describe payload into a usable sqlalchemy.Table.

The type mapping itself belongs to SQLAlchemy, so these do not re-test it. What they
pin is the handling around it: the SERIAL id that must not appear in INSERTs, arrays
whose element type arrives separately, unmapped types degrading instead of raising,
and the id-injection rule that keeps the local Table matching the real one.
"""

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from zamp_sdk.db._table_builder import build_table


def _dataset(columns, primary_key=("id",), name="invoices"):
    return {"table_name": name, "primary_key": list(primary_key), "columns": columns}


def _col(name, type_, **extra):
    return {"name": name, "type": type_, "nullable": True, **extra}


class TestTypeResolution:
    def test_scalars_resolve_through_sqlalchemys_own_table(self):
        table = build_table(
            _dataset(
                [
                    _col("n", "integer"),
                    _col("big", "bigint"),
                    _col("flag", "boolean"),
                    _col("body", "text"),
                    _col("when", "date"),
                ]
            ),
            sa.MetaData(),
        )

        assert isinstance(table.c.n.type, sa.Integer)
        assert isinstance(table.c.big.type, sa.BigInteger)
        assert isinstance(table.c.flag.type, sa.Boolean)
        assert isinstance(table.c.body.type, sa.Text)
        assert isinstance(table.c.when.type, sa.Date)

    def test_varchar_carries_its_length(self):
        table = build_table(_dataset([_col("code", "character varying", length=64)]), sa.MetaData())
        assert table.c.code.type.length == 64

    def test_numeric_carries_precision_and_scale(self):
        table = build_table(_dataset([_col("total", "numeric", precision=12, scale=2)]), sa.MetaData())
        assert (table.c.total.type.precision, table.c.total.type.scale) == (12, 2)

    def test_jsonb_resolves(self):
        table = build_table(_dataset([_col("payload", "jsonb")]), sa.MetaData())
        assert isinstance(table.c.payload.type, postgresql.JSONB)

    def test_array_recurses_on_element_type(self):
        table = build_table(_dataset([_col("tags", "ARRAY", element_type="text")]), sa.MetaData())
        assert isinstance(table.c.tags.type, postgresql.ARRAY)
        assert isinstance(table.c.tags.type.item_type, sa.Text)

    def test_array_falls_back_to_udt_name_when_element_type_is_absent(self):
        """information_schema hides the element type in udt_name as '_text'."""
        table = build_table(_dataset([_col("tags", "ARRAY", udt_name="_text")]), sa.MetaData())
        assert isinstance(table.c.tags.type.item_type, sa.Text)

    def test_unmapped_type_degrades_to_nulltype_rather_than_raising(self):
        """A domain or custom enum must not break the whole table — the column is
        still usable in expressions, just without client-side coercion."""
        table = build_table(_dataset([_col("tier", "aria_customer_tier")]), sa.MetaData())
        assert isinstance(table.c.tier.type, sa.types.NullType)


class TestTimeZoneAwareness:
    """Regression. ``ischema_names`` maps the aware and naive spellings to the SAME
    class — TIMESTAMP for both "timestamp with time zone" and "...without" — so the
    distinction survives only in the ``timezone`` flag, which this builder must set
    itself. SQLAlchemy's own reflection reads the suffix; an offline builder cannot
    inherit that.

    It became load-bearing when the SDK moved to the asyncpg dialect, which renders
    the bind's type into the SQL. A lost flag emits ``$1::TIMESTAMP WITHOUT TIME
    ZONE``, and Postgres then parses an offset-bearing string under that cast,
    discards the offset and keeps the wall clock — storing an instant wrong by the
    offset, with no error. Under the previous psycopg2 dialect both flags rendered
    the same ``%(name)s``, so the bug existed but could not reach the database.
    """

    def test_timestamptz_keeps_its_timezone_flag(self):
        table = build_table(
            _dataset([_col("ts", "timestamp with time zone", udt_name="timestamptz")]),
            sa.MetaData(),
        )
        assert table.c.ts.type.timezone is True

    def test_timetz_keeps_its_timezone_flag(self):
        table = build_table(_dataset([_col("tt", "time with time zone", udt_name="timetz")]), sa.MetaData())
        assert table.c.tt.type.timezone is True

    def test_the_naive_spellings_stay_naive(self):
        table = build_table(
            _dataset(
                [
                    _col("ts", "timestamp without time zone"),
                    _col("tt", "time without time zone"),
                ]
            ),
            sa.MetaData(),
        )
        assert table.c.ts.type.timezone is False
        assert table.c.tt.type.timezone is False

    def test_the_flag_reaches_the_rendered_sql(self):
        """The assertion that actually matters: what Postgres is told to parse."""
        from zamp_sdk.db._compile import compile_statement

        table = build_table(
            _dataset(
                [_col("ts", "timestamp with time zone", udt_name="timestamptz")],
                primary_key=(),
            ),
            sa.MetaData(),
        )
        sql, _ = compile_statement(sa.insert(table).values(ts=dt.datetime(2026, 3, 14, tzinfo=dt.timezone.utc)))
        assert "WITH TIME ZONE" in sql
        assert "WITHOUT TIME ZONE" not in sql


class TestSerialIdHandling:
    def test_serial_id_is_not_an_inserted_column(self):
        """The database assigns it. If the sequence default were attached
        client-side, SQLAlchemy would render it into the INSERT and fight the
        sequence.

        Note ``id`` still appears in the auto-added ``RETURNING`` clause, which is
        exactly what we want — the caller gets the assigned key back. So the
        assertion is about the *inserted columns*, not the whole statement.
        """
        table = build_table(
            _dataset(
                [
                    _col("id", "integer", nullable=False, default="nextval('inv_id_seq'::regclass)"),
                    _col("name", "text"),
                ]
            ),
            sa.MetaData(),
        )

        sql = str(sa.insert(table).values(name="x").compile(dialect=postgresql.dialect()))
        inserted_columns = sql.split("RETURNING")[0]
        assert "id" not in inserted_columns
        assert "RETURNING invoices.id" in sql

    def test_a_plain_default_is_not_treated_as_a_sequence(self):
        table = build_table(
            _dataset([_col("status", "text", default="'pending'::text")], primary_key=()),
            sa.MetaData(),
        )
        assert table.c.status.autoincrement is False

    def test_nullability_is_a_bool_not_a_string(self):
        table = build_table(
            _dataset([_col("name", "text", nullable=False)], primary_key=()),
            sa.MetaData(),
        )
        assert table.c.name.nullable is False
