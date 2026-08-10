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

# information_schema spells an array's type as the literal string "ARRAY" and hides
# the element type in udt_name with a leading underscore ("_text"). The platform
# normalises that into element_type; this is the fallback when it could not.
_ARRAY_TYPE = "array"

# A column whose default calls nextval() is SERIAL/IDENTITY: the database supplies
# the value. Attaching that default client-side would make SQLAlchemy render it into
# INSERTs, so instead the column is marked autoincrement and left default-less.
_SEQUENCE_DEFAULT_PREFIX = "nextval("

# The auto-injected primary key every agent-db dataset carries.
ID_COLUMN = "id"


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
                # A server-generated key must not appear in compiled INSERTs — the
                # database assigns it, and sending NULL or a guess would either fail
                # or fight the sequence.
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
    no ``id``, has a primary key    ``id`` SERIAL NOT NULL is added
    already has an ``id``           left completely alone, whatever its type
    ==============================  ========================================

    Because the server applies the same rule to whatever SQL arrives, adding it here
    first is idempotent rather than a second injection.
    """
    if ID_COLUMN in table.c:
        return table

    has_primary_key = bool(table.primary_key.columns)
    id_column = sa.Column(
        ID_COLUMN,
        sa.Integer,
        primary_key=not has_primary_key,
        nullable=False,
        autoincrement=True,
    )

    # id goes FIRST, matching the server, so the local column order is the real one.
    mirrored = sa.Table(
        table.name,
        sa.MetaData(),
        id_column,
        *(sa.Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in table.c),
    )
    return mirrored
