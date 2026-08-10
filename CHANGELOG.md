# Changelog

## 1.1.0

- **`zamp_sdk.db` — agent-managed database access for scripts.** Write ordinary
  SQLAlchemy; the SDK compiles it and ships it to the platform. No DSN, no
  connection and no credential reaches the script.
  - `datasets.table()` / `datasets.tables()` build live `sqlalchemy.Table` objects
    from the platform's schema, with no database connection. The plural form batches
    into one call.
  - `datasets.execute()` runs one statement; `datasets.transaction()` ships several
    as a single Postgres transaction; `datasets.stream()` pages large reads with a
    keyset cursor.
  - `datasets.create()` / `datasets.drop()` compile SQLAlchemy's `CreateTable` into
    the typed activities. `create()` returns the table carrying the auto-injected
    `id`, which is the object to build expressions from.
  - `AgentDbError` carries `sqlstate` and `statement_index` from the platform.
    `TimeoutError` propagates unwrapped, since the statement may have committed.
- Adds `sqlalchemy ^2.0` as a dependency.

## 0.0.1

- Initial release
- `ActionExecutor.execute()` for running actions via the Zamp HTTP API
- `RetryPolicy` model for configuring action retry behaviour
- Exponential-backoff polling for action results
- Support for explicit `base_url`/`auth_token` or `ZAMP_BASE_URL`/`ZAMP_AUTH_TOKEN` env vars
