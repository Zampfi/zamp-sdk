"""Turning the platform's describe payload into a usable sqlalchemy.Table.

The type mapping itself belongs to SQLAlchemy, so these do not re-test it. What they
pin is the handling around it: the SERIAL id that must not appear in INSERTs, arrays
whose element type arrives separately, unmapped types degrading instead of raising,
and the id-injection rule that keeps the local Table matching the real one.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from zamp_sdk.db._table_builder import apply_id_injection, build_table


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


class TestIdInjectionMirror:
    """The server adds an id to every dataset it creates; the local Table must match,
    or table.c.id would not exist on the object the author is holding."""

    def test_no_id_and_no_pk_gets_id_as_primary_key(self):
        source = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text, nullable=False))
        mirrored = apply_id_injection(source)

        assert "id" in mirrored.c
        assert mirrored.c.id.primary_key is True

    def test_no_id_but_existing_pk_gets_id_without_stealing_the_key(self):
        """Making it a second primary key would be a duplicate-PK error server-side."""
        source = sa.Table(
            "t",
            sa.MetaData(),
            sa.Column("code", sa.Text, primary_key=True),
        )
        mirrored = apply_id_injection(source)

        assert mirrored.c.id.primary_key is False
        assert mirrored.c.code.primary_key is True

    def test_an_authors_own_id_is_left_completely_alone(self):
        source = sa.Table("t", sa.MetaData(), sa.Column("id", sa.Text, primary_key=True))
        mirrored = apply_id_injection(source)

        assert isinstance(mirrored.c.id.type, sa.Text)
        assert mirrored is source

    def test_id_is_the_first_column(self):
        """Matching the server's ordering, so the local column order is the real one."""
        source = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text))
        mirrored = apply_id_injection(source)

        assert list(mirrored.c.keys())[0] == "id"
