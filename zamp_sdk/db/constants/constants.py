"""Shared constants for the agent-DB bridge."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

# ─── Platform action names (the agent-db activities the bridge calls) ───
EXECUTE_SQL = "agent_db_execute_sql"
DESCRIBE_DATASET = "agent_db_describe_dataset"
CREATE_DATASET = "agent_db_create_dataset"
DROP_DATASET = "agent_db_drop_dataset"

# The auto-injected primary key every agent-db dataset carries.
ID_COLUMN = "id"

# Matches the platform's max_result_rows default exactly, so a full page is the
# largest legal single call and a 10k-row read costs one call rather than two.
DEFAULT_PAGE_SIZE = 10000

# Stateless dialects, safe to hold at module scope — a dialect is a compiler, not a
# connection, and can perform no I/O.
#
# COMPILE_DIALECT is the asyncpg dialect, not psycopg2, because asyncpg executes the
# statement server-side. Its paramstyle is ``numeric_dollar``, so it renders ``$1``,
# ``$2`` … directly — the string it returns is the string Postgres parses.
# DDL_DIALECT is the plain postgres dialect, used to compile CreateTable (DDL carries
# no bind parameters, so it needs no driver-specific paramstyle).
COMPILE_DIALECT = postgresql.asyncpg.dialect()
DDL_DIALECT = postgresql.dialect()
