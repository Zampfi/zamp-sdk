"""The one error type the bridge raises.

Deliberately flat. Postgres already has a precise, universally-understood error
vocabulary — SQLSTATE — and both humans and LLMs read it fluently. Wrapping that in
an exception hierarchy of our own would mean maintaining a mapping table, and a
SQLSTATE we had never seen would be classified worse than one we had. So the code
travels through untouched and scripts branch on it if they want to.
"""

from __future__ import annotations

import re

# The platform's failure text is the contract this parses. Pantheon formats a
# statement failure as:
#     "statement 3 failed [sqlstate=23505]: duplicate key value violates ..."
# Both tokens are matched independently and tolerantly, so a message that changes
# shape degrades to a plain message rather than raising while raising.
#
# The trailing \b matters: pantheon writes "sqlstate=unknown" when the driver gave
# it no code, and without the boundary this would happily report the first five
# characters of that word as a SQLSTATE.
_SQLSTATE_RE = re.compile(r"sqlstate[=:]\s*([0-9A-Za-z]{5})\b", re.IGNORECASE)
_STATEMENT_INDEX_RE = re.compile(
    r"statement[\s_](?:index[=:]\s*)?(\d+)",
    re.IGNORECASE,
)
# The ActionExecutor wraps a failed action as "Action <id> <status>: <error>".
_ACTION_RE = re.compile(r"Action\s+(\S+)\s+(\S+?):\s*(.*)", re.DOTALL)


class AgentDbError(RuntimeError):
    """A database operation failed.

    ``sqlstate`` and ``statement_index`` are present when the platform reported
    them, which is the common case for a SQL failure. They are ``None`` for
    failures that never reached Postgres — an authorization refusal, a gate
    rejection, a transport error — so ``is None`` is a meaningful distinction and
    not just missing data.
    """

    def __init__(
        self,
        message: str,
        *,
        sqlstate: str | None = None,
        statement_index: int | None = None,
        action_id: str | None = None,
        action_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.sqlstate = sqlstate
        self.statement_index = statement_index
        self.action_id = action_id
        self.action_status = action_status

    @classmethod
    def from_exception(cls, exc: BaseException) -> "AgentDbError":
        """Build an AgentDbError from whatever the executor raised."""
        text = str(exc)
        action_id = action_status = None
        message = text

        if match := _ACTION_RE.match(text):
            action_id, action_status, message = match.groups()

        sqlstate = m.group(1) if (m := _SQLSTATE_RE.search(text)) else None
        index = int(m.group(1)) if (m := _STATEMENT_INDEX_RE.search(text)) else None

        return cls(
            message.strip(),
            sqlstate=sqlstate,
            statement_index=index,
            action_id=action_id,
            action_status=action_status,
        )

    def __str__(self) -> str:
        parts = [self.message]
        if self.sqlstate:
            parts.append(f"[sqlstate={self.sqlstate}]")
        if self.statement_index is not None:
            parts.append(f"[statement {self.statement_index}]")
        return " ".join(parts)
