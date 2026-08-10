"""The buffering transaction context manager.

``tx.add()`` cannot return rows, and that is the design rather than a limitation:
at ``add()`` time nothing has executed — the body only crosses the wire when the
block exits. Returning a lazy placeholder was considered and rejected, because it
leaks the moment a caller tries to branch on it in Python.
"""

from __future__ import annotations

from typing import Any

from zamp_sdk.db import _actions
from zamp_sdk.db._compile import compile_statement


class Transaction:
    """Buffers statements, then ships them as one body in one Postgres transaction."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_token: str | None = None,
        max_result_rows: int | None = None,
    ) -> None:
        self._statements: list[dict[str, Any]] = []
        self._base_url = base_url
        self._auth_token = auth_token
        self._max_result_rows = max_result_rows
        self.results: list[dict[str, Any]] = []

    def add(self, statement: Any, *, expected_rows: int | None = None) -> int:
        """Buffer one statement. Returns its index in ``results``.

        ``expected_rows`` is the race guard: if the statement affects a different
        number of rows, the whole body rolls back. Use it where a lost update would
        otherwise pass silently — claiming a row, or an update that must not hit zero.
        """
        sql, params = compile_statement(statement)
        entry: dict[str, Any] = {"sql": sql}
        if params:
            entry["params"] = params
        if expected_rows is not None:
            entry["expected_rows"] = expected_rows
        self._statements.append(entry)
        return len(self._statements) - 1

    async def __aenter__(self) -> "Transaction":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            # The block raised, so the caller never finished describing the unit of
            # work. Sending a half-built body would commit an intent nobody stated.
            return False
        if not self._statements:
            return False

        payload: dict[str, Any] = {"statements": self._statements}
        if self._max_result_rows is not None:
            payload["max_result_rows"] = self._max_result_rows

        response = await _actions.call(
            _actions.EXECUTE_SQL,
            payload,
            base_url=self._base_url,
            auth_token=self._auth_token,
        )
        # Positionally aligned with add() order, so results[i] answers statement i.
        self.results = list((response or {}).get("results") or [])
        return False
