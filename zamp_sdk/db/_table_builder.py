"""Build ``sqlalchemy.Table`` objects from the platform's describe payload.

SQLAlchemy normally gets a ``Table`` by reflecting against a live connection. The
bridge has no connection, so the platform supplies the schema and this module
assembles the ``Table`` offline.

**We own none of the type mapping.** ``sqlalchemy.dialects.postgresql.base.ischema_names``
is a dict of ~50 Postgres type names to SQLAlchemy classes, maintained as part of the
library and used by SQLAlchemy's own reflection. This looks names up in it. A name
absent from it resolves to ``NullType``, which is still usable in expressions — just
without client-side coercion — so an unfamiliar type degrades rather than breaking.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.base import ischema_names

from zamp_sdk.db.constants import ID_COLUMN

# information_schema spells an array's type as the literal string "ARRAY" and hides
# the element type in udt_name with a leading underscore ("_text"). The platform
# normalises that into element_type; this is the fallback when it could not.
_ARRAY_TYPE = "array"

# A column whose default calls nextval() is SERIAL/IDENTITY: the database supplies
# the value. Attaching that default client-side would make SQLAlchemy render it into
# INSERTs, so instead the column is marked autoincrement and left default-less.
_SEQUENCE_DEFAULT_PREFIX = "nextval("

# Postgres spells the aware variants as a suffix, and ``ischema_names`` maps both the
# aware and naive spelling to the SAME class — TIMESTAMP for both "timestamp with time
# zone" and "timestamp without time zone" — so the distinction survives only in the
# ``timezone`` flag, which the caller has to set. SQLAlchemy's own reflection reads the
# suffix to do this; an offline builder has to do it explicitly.
#
# Getting it wrong is not cosmetic. The dialect renders the column's type next to the
# placeholder, so a lost flag becomes ``$1::TIMESTAMP WITHOUT TIME ZONE`` — Postgres
# then parses an offset-bearing string under that cast, DISCARDS the offset and keeps
# the wall clock, storing an instant that is wrong by the offset. Silently.
_AWARE_TYPE_SUFFIX = "with time zone"


def _type_of(column: dict[str, Any]) -> Any:
    """Resolve one column's SQLAlchemy type from the describe payload."""
    raw = (column.get("type") or "").strip()
    name = raw.lower()

    if name == _ARRAY_TYPE:
        element = column.get("element_type") or (column.get("udt_name") or "").lstrip("_")
        return postgresql.ARRAY(_type_of({"type": element}))

    factory = ischema_names.get(name)
    if factory is None:
        # Unmapped (a domain, a custom enum, something new). NullType still composes
        # into expressions; only client-side coercion is lost.
        return sa.types.NullType()

    if name.endswith(_AWARE_TYPE_SUFFIX):
        try:
            return factory(timezone=True)
        except TypeError:
            return factory()

    length = column.get("length")
    if length is not None:
        try:
            return factory(length)
        except TypeError:
            return factory()

    precision, scale = column.get("precision"), column.get("scale")
    if precision is not None:
        try:
            return factory(precision, scale) if scale is not None else factory(precision)
        except TypeError:
            return factory()

    return factory()


def build_table(dataset: dict[str, Any], metadata: sa.MetaData) -> sa.Table:
    """Assemble one ``sa.Table`` from a describe-payload dataset entry."""
    name = dataset.get("table_name") or dataset["name"]
    primary_key = set(dataset.get("primary_key") or ())

    columns = []
    for column in dataset.get("columns", ()):
        column_name = column["name"]
        default = column.get("default")
        is_serial = bool(default) and str(default).startswith(_SEQUENCE_DEFAULT_PREFIX)

        columns.append(
            sa.Column(
                column_name,
                _type_of(column),
                primary_key=column_name in primary_key,
                nullable=bool(column.get("nullable", True)),
                autoincrement=is_serial,
            )
        )

    # extend_existing so a script that describes the same table twice updates the
    # object rather than raising on a duplicate definition in the shared MetaData.
    return sa.Table(name, metadata, *columns, extend_existing=True)


def apply_id_injection(table: sa.Table) -> sa.Table:
    """Mirror the server's ``inject_id_column`` rule onto a locally-built Table.

    The server adds an ``id`` primary key to every dataset it creates. If the local
    ``sa.Table`` did not also get one, ``table.c.id`` would not exist on the object
    the author is holding, and every expression referencing it would fail against a
    table that really does have the column.

    The three rules are the server's, applied identically:

    ==============================  ========================================
    The author's Table              Result
    ==============================  ========================================
    no ``id``, no primary key       ``id`` SERIAL PRIMARY KEY is added
    no ``id``, has a primary key    a generated-identity ``id`` is added
    already has an ``id``           left completely alone, whatever its type
    ==============================  ========================================

    Because the server applies the same rule to whatever SQL arrives, adding it here
    first is idempotent rather than a second injection.

    Everything else the author declared — defaults, CHECK and UNIQUE constraints,
    foreign keys — is carried over verbatim, because the DDL compiled from this
    mirror *is* the dataset that gets created.
    """
    if ID_COLUMN in table.c:
        return table

    # The mirror needs its own MetaData, so any sibling a foreign key points at has to
    # come along or the reference would not resolve when the DDL is compiled.
    mirror_metadata = sa.MetaData()
    for sibling in list(table.metadata.tables.values()):
        if sibling is not table:
            sibling.to_metadata(mirror_metadata)

    # Columns first, then constraints, in that order and for the reason SQLAlchemy's
    # own Table.to_metadata does it: a constraint copy resolves its column expressions
    # against target_table, and a copy made with no target would resolve them against
    # the *source* columns and auto-attach itself back onto the author's Table.
    #
    # id goes FIRST, matching the server, so the local column order is the real one.
    mirrored = sa.Table(
        table.name,
        mirror_metadata,
        _id_column(has_primary_key=bool(table.primary_key.columns)),
        # _copy is what to_metadata uses; there is no public per-column equivalent,
        # and a Column cannot belong to two Tables.
        *(column._copy() for column in table.c),
    )
    for constraint in table.constraints:
        if _is_regenerated(constraint):
            continue
        mirrored.append_constraint(constraint._copy(target_table=mirrored))
    return mirrored


def _is_regenerated(constraint: Any) -> bool:
    """Whether attaching the copied columns already recreated this constraint.

    Copying it a second time would emit the same clause twice, and Postgres rejects a
    CREATE TABLE that names one constraint twice.
    """
    return (
        # The primary key rides on the columns' own primary_key flags.
        isinstance(constraint, sa.PrimaryKeyConstraint)
        # Produced by a column's type (Boolean's 0/1 CHECK, Enum's IN list).
        or constraint._type_bound
        # Produced by a column's own unique=/index= flag, which _copy carries over.
        or constraint._column_flag
    )


def _id_column(*, has_primary_key: bool) -> sa.Column:
    """The injected key column, in the only spelling that renders a generator.

    SQLAlchemy's postgres dialect renders SERIAL only for the column that *is* the
    table's primary key. Alongside an author's own key it would compile to a bare
    ``INTEGER NOT NULL`` with no default, and every INSERT would fail its not-null
    check on a column nobody is meant to supply. IDENTITY is the standard-SQL
    spelling of the same generator and renders on any column.
    """
    if has_primary_key:
        return sa.Column(ID_COLUMN, sa.Integer, sa.Identity(), nullable=False)
    return sa.Column(ID_COLUMN, sa.Integer, primary_key=True, nullable=False, autoincrement=True)
