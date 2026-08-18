"""SQLAlchemy expression → ``(sql, args)``.

The whole compile step, and the reason the bridge is not an ORM: SQLAlchemy already
is one. This module asks it to render for the driver the server actually runs, and
then does nothing to the SQL it gets back.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ClauseElement

from zamp_sdk.db.constants import COMPILE_DIALECT


def compile_statement(statement: ClauseElement) -> tuple[str, list[Any]]:
    """Render a SQLAlchemy statement to ``$n`` SQL plus its arguments, in order.

    Three decisions are load-bearing:

    - ``render_postcompile=True`` expands ``IN``-lists into one bind parameter per
      element. Without it the SQL carries a single placeholder token that stands for
      the whole list, which no driver can bind.
    - **Never** ``literal_binds``. Inlining values into the SQL text loses type
      fidelity, requires reimplementing Postgres literal escaping for every type,
      and raises outright for types with no literal processor. Values stay arguments.
    - ``_bind_processors`` is applied, not skipped. These are the per-type converters
      SQLAlchemy's own execution context runs before handing values to the driver —
      ``json.dumps`` for JSON/JSONB, and the array and enum conversions. Reading
      ``compiled.params`` alone gives the *pre*-conversion values, which is how a
      ``dict`` bound to a jsonb column reaches asyncpg as a dict and fails.

    ``positiontup`` is the bind names in placeholder order, so a parameter referenced
    twice appears once and reuses its ``$n`` — the compiler's job, not ours.
    """
    compiled = statement.compile(
        dialect=COMPILE_DIALECT,
        compile_kwargs={"render_postcompile": True},
    )
    # DDL compiles to a PGDDLCompiler, which has neither attribute. A CREATE TABLE
    # carries no binds, so the empty defaults are the right answer, not a guard.
    positions = getattr(compiled, "positiontup", None) or ()
    params = getattr(compiled, "params", None) or {}
    processors = getattr(compiled, "_bind_processors", None) or {}

    args = [_to_wire(processors[name](params[name]) if name in processors else params[name]) for name in positions]
    return str(compiled), args


def _to_wire(value: Any) -> Any:
    """Render the scalars JSON has no syntax for as the text Postgres accepts.

    This is transport encoding, not translation: arguments cross to the platform as
    JSON, and JSON has no timestamp, numeric, UUID or bytes. Each travels as the
    string form Postgres's own input function parses, and the placeholder already
    carries its type — the dialect printed ``$1::TIMESTAMP WITH TIME ZONE`` — so
    nothing has to be inferred at the other end.

    ``datetime`` is checked before ``date`` because it is a subclass of it.
    """
    if isinstance(value, dt.timedelta):
        # Postgres reads this as an interval literal. isoformat() is not an option:
        # timedelta has none, and json.dumps would reach it raw and raise.
        return f"{value.days} days {value.seconds} seconds {value.microseconds} microseconds"
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    return value
