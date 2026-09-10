# Changelog

## 1.1.2

- **`channel_context` is the only channel input.** `emit_log` and
  `request_user_input` no longer put a `context` object in an action's params. The
  platform stamps the channel into the params itself, from the verified execution
  token, and the actions now require it — a caller-supplied one was already not
  read. Nothing changes for callers: the context still reaches the platform as the
  request body's `channel_context`, attached by `ActionExecutor` as before.
  - `_emit_context()` is gone, along with the `context` key it filled.
  - `request_user_input` still reads `ZAMP_RUN_ID` to carry `run_id` on the
    post-action, so the platform can correlate the re-run.

## 1.1.1

- **Faster action polling.** The client poll loop sleeps its interval before the
  first `GET /actions/{id}`, so the previous 1.0s initial interval added a ~700ms
  dead wait on every fast action (agent-managed DB calls complete server-side in
  ~300ms). Lowered `POLL_INITIAL_INTERVAL_SECONDS` 1.0 → 0.1 and gentled
  `POLL_BACKOFF_COEFFICIENT` 2.0 → 1.5, so a ~300ms action now returns in ~0.5s
  instead of ~1.0s. Max interval (30s) and the 1h poll ceiling are unchanged.
  The POST-create retry-on-5xx path was split onto its own `POST_RETRY_*`
  constants (kept at the original 1.0s / ×2.0), so this poll tuning no longer
  accelerates retries into an already-failing create endpoint.

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
