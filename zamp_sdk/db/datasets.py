"""The authoring surface: six calls over the agent-DB activities.

A script writes ordinary SQLAlchemy; this module compiles it and ships it. It is
**not** a security boundary — identity, the DDL gate, row caps and timeouts are all
enforced server-side, and a caller who bypassed this module entirely would meet
exactly the same rules. It is also not a connection: it never opens a socket and
never holds a DSN.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import sqlalchemy as sa

from zamp_sdk.db import _actions
from zamp_sdk.db._compile import compile_statement
from zamp_sdk.db._table_builder import ID_COLUMN, apply_id_injection, build_table
from zamp_sdk.db._transaction import Transaction
from zamp_sdk.db.errors import AgentDbError

# Matches the platform's max_result_rows default exactly, so a full page is the
# largest legal single call and a 10k-row read costs one call rather than two.
DEFAULT_PAGE_SIZE = 10000


async def table(
    name: str,
    *,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> sa.Table:
    """Fetch one dataset's schema and return a live ``sqlalchemy.Table``."""
    tables = await _describe([name], base_url=base_url, auth_token=auth_token)
    if name not in tables:
        raise AgentDbError(f"dataset {name!r} was not found, or you have no access to it.")
    return tables[name]


async def tables(
    names: list[str],
    *,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> dict[str, sa.Table]:
    """Fetch several datasets' schemas in **one** call.

    A script touching nine tables describes them once rather than nine times. The
    returned tables share one ``MetaData``, so joins across them compose.
    """
    return await _describe(names, base_url=base_url, auth_token=auth_token)


async def _describe(
    names: list[str],
    *,
    base_url: str | None,
    auth_token: str | None,
) -> dict[str, sa.Table]:
    response = await _actions.call(
        _actions.DESCRIBE_DATASET,
        {"table_names": names},
        base_url=base_url,
        auth_token=auth_token,
    )
    metadata = sa.MetaData()
    built: dict[str, sa.Table] = {}
    for dataset in (response or {}).get("datasets") or []:
        built_table = build_table(dataset, metadata)
        built[built_table.name] = built_table
    return built


async def execute(
    statement: Any,
    *,
    expected_rows: int | None = None,
    max_result_rows: int | None = None,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> list[dict[str, Any]]:
    """Run one statement and return its rows.

    This is the single-statement case, not the "non-transactional" one — it is still
    one call and one Postgres transaction.
    """
    sql, params = compile_statement(statement)
    entry: dict[str, Any] = {"sql": sql}
    if params:
        entry["params"] = params
    if expected_rows is not None:
        entry["expected_rows"] = expected_rows

    payload: dict[str, Any] = {"statements": [entry]}
    if max_result_rows is not None:
        payload["max_result_rows"] = max_result_rows

    response = await _actions.call(_actions.EXECUTE_SQL, payload, base_url=base_url, auth_token=auth_token)
    results = (response or {}).get("results") or []
    return list(results[0].get("rows") or []) if results else []


def transaction(
    *,
    max_result_rows: int | None = None,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> Transaction:
    """Buffer several statements and ship them as one transaction.

    ``async with datasets.transaction() as tx:`` — every ``tx.add()`` inside the
    block lands together or not at all. Results arrive on ``tx.results`` after the
    block exits, aligned with ``add()`` order.
    """
    return Transaction(base_url=base_url, auth_token=auth_token, max_result_rows=max_result_rows)


async def stream(
    statement: Any,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    key: str = ID_COLUMN,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Read a large result in pages, using a keyset cursor.

    Keyset, not ``OFFSET``: ``OFFSET n`` makes Postgres scan and discard n rows, so
    cost grows quadratically across pages — and rows shift under concurrent writes,
    which silently skips and duplicates. A keyset cursor is stable and O(page).

    Requires an orderable unique NOT NULL key, defaulting to the injected ``id``, and
    a statement that carries no ORDER BY, LIMIT or OFFSET of its own — each of those
    would fight the cursor rather than compose with it, so they are refused instead
    of being silently overridden. Each page is one call, so ``page_size`` may not
    exceed the server's ``max_result_rows``.
    """
    key_column = _key_column(statement, key)
    _reject_conflicting_clauses(statement, key)
    cursor: Any = None

    while True:
        page_statement = statement
        if cursor is not None:
            page_statement = page_statement.where(key_column > cursor)
        page_statement = page_statement.order_by(key_column).limit(page_size)

        rows = await execute(
            page_statement,
            max_result_rows=page_size,
            base_url=base_url,
            auth_token=auth_token,
        )
        if rows:
            yield rows
        # A short page means the last one: there is no further row past the cursor.
        if len(rows) < page_size:
            return
        cursor = rows[-1][key_column.name]
        if cursor is None:
            # Postgres sorts NULLs last, so `key > NULL` is NULL and matches nothing:
            # the cursor can never advance past this page. Left alone the loop would
            # re-fetch the same page forever.
            raise AgentDbError(
                f"stream() cannot page past a NULL {key_column.name!r}. Page on a "
                f"NOT NULL unique column via key='<column>'."
            )


def _key_column(statement: Any, key: str) -> Any:
    """Find the cursor column among the statement's *selected* columns.

    The projection, not the source table: the cursor is read back out of the rows the
    statement returns, so a key the table has but the SELECT list omits would page on
    a value that never arrives.
    """
    for column in getattr(statement, "selected_columns", ()) or ():
        if getattr(column, "name", None) == key:
            if getattr(column, "nullable", False):
                # NULLs sort last, so the cursor either stops advancing on them or
                # filters them out — the key is unusable either way. Rejected up
                # front, while it still costs nothing.
                raise AgentDbError(
                    f"stream() cannot page on {key!r} because it is nullable: "
                    f"Postgres sorts NULLs last, so the cursor would never reach the "
                    f"rows past them. Page on a NOT NULL unique column via "
                    f"key='<column>'."
                )
            return column
    raise AgentDbError(
        f"stream() needs an orderable unique column to page on and could not find "
        f"{key!r} among the statement's selected columns. Select it, or pass "
        f"key='<column>'."
    )


def _reject_conflicting_clauses(statement: Any, key: str) -> None:
    """Refuse a statement whose own paging clauses would corrupt the cursor.

    SQLAlchemy exposes no public getter for these three, so the attributes ``Select``
    stores them in are read directly.
    """
    if getattr(statement, "_order_by_clauses", ()):
        raise AgentDbError(
            f"stream() orders every page by {key!r} to page on it, and order_by() "
            f"appends rather than replaces — the statement's own ordering would lead, "
            f"so the cursor would skip and repeat rows. Drop the order_by(), or read "
            f"the ordered result with execute()."
        )
    if getattr(statement, "_limit_clause", None) is not None:
        raise AgentDbError(
            "stream() sets its own LIMIT per page, which would replace the "
            "statement's and read far more rows than it asked for. Drop the limit(), "
            "or read the bounded result with execute()."
        )
    if getattr(statement, "_offset_clause", None) is not None:
        raise AgentDbError(
            "stream() pages with a keyset cursor, so an OFFSET would be re-applied on "
            "top of every page and silently drop rows. Drop the offset() — stream() "
            "already reads the whole result."
        )


async def create(
    table_object: sa.Table,
    *,
    if_exists: str = "error",
    base_url: str | None = None,
    auth_token: str | None = None,
) -> sa.Table:
    """Create a dataset from a ``sa.Table`` definition.

    Returns the **mirrored** table — the one carrying the auto-injected ``id`` — so
    the object the caller goes on to build expressions from matches the table that
    now exists. Use the return value, not the input.
    """
    from sqlalchemy.schema import CreateTable

    mirrored = apply_id_injection(table_object)
    create_sql = str(CreateTable(mirrored).compile(dialect=_dialect()))

    await _actions.call(
        _actions.CREATE_DATASET,
        {"create_sql": create_sql.strip(), "if_exists": if_exists},
        base_url=base_url,
        auth_token=auth_token,
    )
    return mirrored


async def drop(
    table_or_name: sa.Table | str,
    *,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> None:
    """Delete a dataset and all of its rows. Irreversible."""
    name = table_or_name.name if isinstance(table_or_name, sa.Table) else table_or_name
    await _actions.call(
        _actions.DROP_DATASET,
        {"table_name": name},
        base_url=base_url,
        auth_token=auth_token,
    )


def _dialect() -> Any:
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()
