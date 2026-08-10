"""SQLAlchemy expression → ``(sql, params)``.

The whole compile step, and the reason the bridge is not an ORM: SQLAlchemy already
is one. This module only asks it to render, and takes care over three details that
would otherwise produce SQL the server cannot bind.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects import postgresql

from zamp_sdk.db.errors import AgentDbError

# Stateless — a dialect is a compiler, not a connection. Nothing here can perform
# I/O, which is what makes it safe to hold at module scope.
_DIALECT = postgresql.dialect()

# The pyformat dialect escapes every literal ``%`` in the rendered SQL as ``%%``.
_ESCAPED_PERCENT = "%%"

# The cast wrapped around a placeholder whose value had to be stringified. Doubled on
# purpose: Postgres assigns a parameter the type of a cast applied directly to it, so
# a single ``CAST($1 AS TIMESTAMP)`` would put the driver right back to expecting a
# Python datetime. Casting to TEXT first pins the parameter as text.
_TEXT_CAST = "CAST(CAST({token} AS TEXT) AS {pg_type})"
# Postgres has no text → bytea cast; decode() is the conversion, and its first
# argument being text pins the parameter the same way.
_BYTEA_CAST = "DECODE(CAST({token} AS TEXT), 'hex')"
_BYTEA = "BYTEA"

_JSON_SCALARS = (str, int, float, bool, type(None))


def compile_statement(statement: Any) -> tuple[str, dict[str, Any]]:
    """Render a SQLAlchemy statement to pyformat SQL plus its bound parameters.

    Four decisions are load-bearing:

    - ``render_postcompile=True`` expands ``IN``-lists into one bind parameter per
      element. Without it the SQL carries a single placeholder token that stands for
      the whole list, which no driver can bind.
    - **Never** ``literal_binds``. Inlining values into the SQL text loses type
      fidelity, requires reimplementing Postgres literal escaping for every type,
      and raises outright for types with no literal processor. Values stay in
      params, always — including the ones stringified by ``_encode_param``, which
      keep their type through a cast on the placeholder rather than in the value.
    - The paramstyle is pyformat (``%(name)s``), which is what the server expects,
      and bind names survive the round trip unchanged.
    - A statement with no binds has its ``%%`` un-doubled here, because the server
      only does that for a statement that carries params.
    """
    compiled = statement.compile(
        dialect=_DIALECT,
        compile_kwargs={"render_postcompile": True},
    )
    sql = str(compiled)
    params: dict[str, Any] = {}

    for name, value in compiled.params.items():
        encoded, pg_type = _encode_param(name, value)
        params[name] = encoded
        if pg_type is not None:
            token = f"%({name})s"
            cast = _BYTEA_CAST if pg_type == _BYTEA else _TEXT_CAST
            # The token carries its own delimiters, so no other bind name can be a
            # prefix match: "%(vendor_1)s" cannot occur inside "%(vendor_11)s".
            sql = sql.replace(token, cast.format(token=token, pg_type=pg_type))

    if not params:
        # The server only un-doubles ``%%`` when params are present, using that as its
        # signal that the SQL came from a pyformat compiler. With no binds there is no
        # ``%(name)s`` token left to protect, so the escaping is undone here instead —
        # otherwise a literal percent would reach Postgres doubled.
        sql = sql.replace(_ESCAPED_PERCENT, "%")

    return sql, params


def _encode_param(name: str, value: Any) -> tuple[Any, str | None]:
    """Return one bound value as JSON, plus the Postgres type it must be cast back to.

    Bound values cross the wire as JSON, and the ordinary Postgres scalars have no
    JSON equivalent — timestamps, dates, times, numerics, UUIDs, bytea. Each travels
    as its string form and is cast back to its real type server-side, so the driver
    still binds a parameter of the right type and nothing is inlined into the SQL. A
    value JSON already carries needs no cast, and reports ``None``.

    ``datetime`` is checked before ``date`` because it is a subclass of it.
    """
    if isinstance(value, dt.datetime):
        return value.isoformat(), "TIMESTAMP WITH TIME ZONE" if value.tzinfo else "TIMESTAMP"
    if isinstance(value, dt.date):
        return value.isoformat(), "DATE"
    if isinstance(value, dt.time):
        return value.isoformat(), "TIME WITH TIME ZONE" if value.tzinfo else "TIME"
    if isinstance(value, Decimal):
        return str(value), "NUMERIC"
    if isinstance(value, uuid.UUID):
        return str(value), "UUID"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex(), _BYTEA
    if _is_json_safe(value):
        return value, None
    raise AgentDbError(
        f"parameter {name!r} is a {type(value).__name__}, which cannot be sent to the "
        f"platform — bound values travel as JSON. Convert it to a string, number or "
        f"boolean first."
    )


def _is_json_safe(value: Any) -> bool:
    """Whether ``json.dumps`` can encode the value exactly as it stands."""
    if isinstance(value, _JSON_SCALARS):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_safe(item) for key, item in value.items())
    return False
