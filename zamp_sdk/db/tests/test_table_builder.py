"""Turning the platform's describe payload into a usable sqlalchemy.Table.

The type mapping itself belongs to SQLAlchemy, so these do not re-test it. What they
pin is the handling around it: the SERIAL id that must not appear in INSERTs, arrays
whose element type arrives separately, unmapped types degrading instead of raising,
and the id-injection rule that keeps the local Table matching the real one.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from zamp_sdk.db._table_builder import apply_id_injection, build_table


def _ddl(table):
    """The exact string datasets.create() ships as create_sql."""
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))


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


class TestInjectedIdGeneratesItsOwnValues:
    """The DDL compiled from the mirror *is* the dataset, so the injected key has to
    render a generator. Without one the column is NOT NULL with no default and no
    sequence, and every INSERT — which omits ``id``, because nobody is meant to supply
    it — fails 23502 against a dataset create() just reported as successful."""

    def test_with_no_author_key_the_id_is_serial(self):
        source = sa.Table("t", sa.MetaData(), sa.Column("name", sa.Text))

        assert "id SERIAL NOT NULL" in _ddl(apply_id_injection(source))

    def test_alongside_an_author_key_the_id_is_a_generated_identity(self):
        """SQLAlchemy's postgres dialect renders SERIAL only for the column that *is*
        the primary key, so next to an author's own key the spelling has to be
        IDENTITY — which renders on any column and implies NOT NULL."""
        source = sa.Table(
            "orders",
            sa.MetaData(),
            sa.Column("order_no", sa.Text, primary_key=True),
            sa.Column("total", sa.Integer),
        )

        ddl = _ddl(apply_id_injection(source))

        assert "id INTEGER GENERATED BY DEFAULT AS IDENTITY" in ddl
        assert "id INTEGER NOT NULL," not in ddl
        assert "PRIMARY KEY (order_no)" in ddl

    def test_the_generated_id_is_never_an_inserted_column(self):
        """The other half of the same contract: the database assigns it, so if the
        mirror let SQLAlchemy render it into INSERTs it would fight the generator."""
        source = sa.Table(
            "orders",
            sa.MetaData(),
            sa.Column("order_no", sa.Text, primary_key=True),
            sa.Column("total", sa.Integer),
        )
        mirrored = apply_id_injection(source)

        sql = str(sa.insert(mirrored).values(order_no="A1", total=5).compile(dialect=postgresql.dialect()))

        assert sql.split("RETURNING")[0] == "INSERT INTO orders (order_no, total) VALUES (%(order_no)s, %(total)s)"


class TestMirrorPreservesWhatTheAuthorDeclared:
    """The mirror is the CREATE TABLE. Anything it drops is silently absent from the
    real dataset, while create() still reports success — a duplicate then slips past a
    unique= the author declared, and an upsert inferring that index fails 42P10."""

    @staticmethod
    def _source():
        metadata = sa.MetaData()
        sa.Table("vendors", metadata, sa.Column("id", sa.Integer, primary_key=True))
        return sa.Table(
            "invoices",
            metadata,
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("now()")),
            sa.Column("amount", sa.Numeric(12, 2)),
            sa.Column("status", sa.String(20)),
            sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id")),
            sa.CheckConstraint("amount >= 0", name="ck_amount"),
            sa.UniqueConstraint("email", "status", name="uq_email_status"),
        )

    def test_defaults_checks_uniques_and_foreign_keys_all_survive(self):
        ddl = _ddl(apply_id_injection(self._source()))

        assert "DEFAULT now()" in ddl
        assert "CONSTRAINT ck_amount CHECK (amount >= 0)" in ddl
        assert "CONSTRAINT uq_email_status UNIQUE (email, status)" in ddl
        assert "UNIQUE (email)" in ddl
        assert "FOREIGN KEY(vendor_id) REFERENCES vendors (id)" in ddl

    def test_nothing_is_declared_twice(self):
        """A constraint the copied columns already regenerate must not be copied a
        second time: Postgres rejects a CREATE TABLE naming one constraint twice."""
        ddl = _ddl(apply_id_injection(self._source()))

        assert ddl.count("UNIQUE (email)") == 1
        assert ddl.count("uq_email_status") == 1
        assert ddl.count("FOREIGN KEY") == 1
        assert ddl.count("ck_amount") == 1

    def test_the_authors_table_is_left_untouched(self):
        """Copying a constraint with no target resolves it against the *source*
        columns and auto-attaches it back onto the author's Table."""
        source = self._source()
        before = _ddl(source)

        apply_id_injection(source)

        assert _ddl(source) == before

    def test_creating_the_same_table_twice_compiles_the_same_ddl(self):
        """The direct consequence of the above: a second create() on the same object
        would otherwise emit uq_email_status twice and be rejected outright."""
        source = self._source()

        assert _ddl(apply_id_injection(source)) == _ddl(apply_id_injection(source))

    def test_a_composite_foreign_key_is_carried_over(self):
        metadata = sa.MetaData()
        sa.Table(
            "vendors",
            metadata,
            sa.Column("a", sa.Integer, primary_key=True),
            sa.Column("b", sa.Integer, primary_key=True),
        )
        source = sa.Table(
            "invoices",
            metadata,
            sa.Column("x", sa.Integer),
            sa.Column("y", sa.Integer),
            sa.ForeignKeyConstraint(["x", "y"], ["vendors.a", "vendors.b"]),
        )

        assert "FOREIGN KEY(x, y) REFERENCES vendors (a, b)" in _ddl(apply_id_injection(source))

    def test_a_type_bound_check_survives_exactly_once(self):
        """A non-native Enum's CHECK belongs to the column's type, which regenerates
        it on the copy — so it must be carried by the column and not copied again."""
        source = sa.Table(
            "t",
            sa.MetaData(),
            sa.Column("tier", sa.Enum("a", "b", name="tier_enum", native_enum=False, create_constraint=True)),
        )

        assert _ddl(apply_id_injection(source)).count("CONSTRAINT tier_enum CHECK") == 1
