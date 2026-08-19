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
