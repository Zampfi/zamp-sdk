# Changelog

## 1.1.3

- **Inline execution on the API path.** `ActionExecutor.execute(...,
  execution_mode=ExecutionMode.INLINE)` sends `execution_mode: "INLINE"` on
  `POST /actions`; the platform runs the action inside that request and answers
  with its terminal state, so the result comes back from the one call with no
  `GET /actions/{id}` polling. `SYNC` / `ASYNC` / unspecified keep today's
  Temporal-backed behaviour.
  - An inline `POST` is never retried on a 5xx: the action may already have run,
    and a retry would re-run a non-idempotent write. The Temporal-path `POST`
    retries as before.
  - A `FAILED` / `TIMED_OUT` inline answer raises the same `RuntimeError` the poll
    path raises for the same outcome; the terminal-state handling is shared.
  - A `RUNNING` answer — an older platform that dropped the field — falls back to
    polling, so a version skew costs latency, not correctness.
  - The inline request carries its own timeout: the caller's
    `action_start_to_close_timeout`, clamped to the platform's 25s inline ceiling,
    plus a 5s margin so the platform's own `TIMED_OUT` arrives first.
  - The SDK's default `RetryPolicy` is not sent with `INLINE`. A policy the caller
    passes explicitly still is, and the platform refuses it with the reason.
- **`HttpClientError` carries the platform's message.** A non-2xx response's
  `message` (flat, or under `error`) is appended to the exception message, so a 400
  from the inline allow-list reads as the platform wrote it rather than as
  `HTTP 400`.
- **`zamp_sdk.db` runs inline.** `datasets.table()` / `tables()`, `execute()`,
  `stream()` and `transaction()` pass `ExecutionMode.INLINE` through
  `actions.call`; `create()` and `drop()` stay on the durable path. The rules of
  `actions.call` are unchanged — no retry or timeout override is ever sent; the
  transport is a different axis.

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
