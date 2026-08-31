"""Agent-managed database access for scripts.

Write ordinary SQLAlchemy; the bridge compiles it and ships it to the platform. No
DSN, no connection, no credential ever reaches the script.

    from zamp_sdk.db import datasets, select

    invoices = await datasets.table("invoices")
    rows = await datasets.execute(select(invoices).where(invoices.c.status == "open"))

**Why the SQLAlchemy builders are re-exported here.** Code that runs in the platform
code-executor cannot ``import sqlalchemy`` directly — the executor exposes a curated set of
modules and strips anything else. ``zamp_sdk`` is exposed, so the query-construction surface
a script needs is re-exported from ``zamp_sdk.db`` and reached as ``from zamp_sdk.db import
select, insert, pg_insert, Table, Column, ...``. Only construction/typing names are here:
``create_engine``/``Engine``/``Connection``/``Session`` are deliberately NOT re-exported —
the bridge never opens a connection, and nothing in a script should be able to.
"""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Interval,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Sequence,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    and_,
    asc,
    bindparam,
    case,
    cast,
    delete,
    desc,
    distinct,
    false,
    func,
    insert,
    literal,
    literal_column,
    not_,
    null,
    or_,
    select,
    text,
    true,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert

from zamp_sdk.db import datasets
from zamp_sdk.db.utils import AgentDbError

__all__ = [
    "AgentDbError",
    "datasets",
    # SQLAlchemy query construction (re-exported so code-executor scripts can build
    # statements without importing sqlalchemy directly)
    "select",
    "insert",
    "update",
    "delete",
    "pg_insert",
    "and_",
    "or_",
    "not_",
    "case",
    "cast",
    "literal",
    "literal_column",
    "bindparam",
    "text",
    "func",
    "distinct",
    "tuple_",
    "asc",
    "desc",
    "null",
    "true",
    "false",
    "Table",
    "Column",
    "MetaData",
    "ForeignKey",
    "Index",
    "UniqueConstraint",
    "PrimaryKeyConstraint",
    "CheckConstraint",
    "Sequence",
    "Identity",
    "Integer",
    "BigInteger",
    "SmallInteger",
    "Numeric",
    "Float",
    "Boolean",
    "String",
    "Text",
    "LargeBinary",
    "Date",
    "DateTime",
    "Time",
    "Interval",
    "Enum",
    "JSON",
    "ARRAY",
    "JSONB",
    "UUID",
]
