"""SQLAlchemy expression → ``(sql, params)``.

The whole compile step, and the reason the bridge is not an ORM: SQLAlchemy already
is one. This module only asks it to render, and takes care over three details that
would otherwise produce SQL the server cannot bind.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects import postgresql

# Stateless — a dialect is a compiler, not a connection. Nothing here can perform
# I/O, which is what makes it safe to hold at module scope.
_DIALECT = postgresql.dialect()


def compile_statement(statement: Any) -> tuple[str, dict[str, Any]]:
    """Render a SQLAlchemy statement to pyformat SQL plus its bound parameters.

    Three decisions are load-bearing:

    - ``render_postcompile=True`` expands ``IN``-lists into one bind parameter per
      element. Without it the SQL carries a single placeholder token that stands for
      the whole list, which no driver can bind.
    - **Never** ``literal_binds``. Inlining values into the SQL text loses type
      fidelity, requires reimplementing Postgres literal escaping for every type,
      and raises outright for types with no literal processor. Values stay in
      params, always.
    - The paramstyle is pyformat (``%(name)s``), which is what the server expects,
      and bind names survive the round trip unchanged.
    """
    compiled = statement.compile(
        dialect=_DIALECT,
        compile_kwargs={"render_postcompile": True},
    )
    return str(compiled), dict(compiled.params)
