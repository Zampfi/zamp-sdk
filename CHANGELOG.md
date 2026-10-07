# Changelog

## 1.5.0

- **A rate-limit refusal is a typed `RateLimitedError`.** When an organization (or one user or
  agent) is over its rate limit for a kind of work, the platform answers `POST /actions` with
  HTTP 429. The SDK now reads that answer: the error's `message` is the platform's own text (who
  is over which limit, how long to wait, not to retry in a loop), and `retry_after` (seconds),
  `check` (`"org"` / `"principal"`) and `limit_class` (`"sdk.action"`, `"sdk.run"`, ...) come
  from the body and the `Retry-After` header. The header is read as seconds or as an HTTP-date,
  which a proxy in front of the platform may send; a date is counted from now, never negative.
  - **Existing handlers keep working.** It subclasses `HttpClientError` with `status_code`
    429, and its text still starts `HTTP 429 from <url>`, now followed by the platform's text.
- **Creating an action retries a 429 briefly, then raises it.** A 429 means nothing was started,
  so sending the create again cannot run the action twice: at most 3 refused attempts, each wait
  honouring `Retry-After`, within 60 s of waiting on refusals. No retry when the platform names no
  wait, which it does when a retry could never fit the limit. This covers every action call made
  over the API, the SDK's own log calls included.
- **A 429 while polling is never terminal.** A refused `GET /actions/{id}` says nothing about the
  action, which is still running: the poll waits as told and carries on, within the same overall
  timeout as before.
- **A 5xx on create is retried for 5 minutes, not an hour,** on a budget independent of the 429
  one (a create that meets both can be sent more than 3 times), and every retry wait (5xx or 429,
  create or poll) is stretched by up to 50% at random, never shortened, so callers that failed
  together do not all come back together. Each retry the platform admits counts against the
  org's limit, so an hour of them through an outage spends that budget for nothing.
- **`AgentDbError.status_code`** — the HTTP status when a database call failed as an HTTP error
  (429 for a rate limit), `None` otherwise, so a script can tell a refusal from a SQL failure.
- **`User-Agent: zamp-sdk/<version>`** on every request.
- **`rate_limit_refusal(value)` finds a refusal that arrived in-band.** Some refusals are not
  HTTP errors: a spawned agent task the platform refuses completes with
  `error="RATE_LIMITED: ..."`, and inside the code executor a refused call returns a FAILED
  envelope with that error. Those still arrive exactly as before — the SDK does not turn a
  completed action into an exception, or change how a failure surfaces — and
  `rate_limit_refusal()` returns a `RateLimitedError` for any of them, for a raised error that is
  or was raised from one, or `None`. A result or envelope validated into a `return_type` model
  is read too, as long as the model keeps its `error` field.

## 1.4.0

- **`ChannelContext.tool_execution_mode` — whether a tool call runs in the agent's turn or in the
  background.** `ToolExecutionMode.SYNC` (the default) or `ToolExecutionMode.ASYNC`. Inside a
  background tool call the channel and `message_id` are still the conversation or task message
  the call started from, and `tool_call_id` is the background call's own id; the platform sets
  the mode and validates it wherever a context enters, so a caller cannot claim it.
  - **Backwards compatible both ways.** A context without the field is a sync one, so every
    existing caller and payload is unchanged; an older SDK that sees the field ignores it.
    The SDK only sends the field on an action request when it is `async`.
  - In a sandbox it arrives as the optional `ZAMP_TOOL_EXECUTION_MODE` variable, read by
    `resolve_context` when set. It is not one of the six channel variables that are all-or-none.

## 1.3.0

- **Actions run in the caller's branch.** A script running inside a branch now keeps its action
  calls — dataset queries, spawned tasks, file actions — in that branch instead of main. The
  runtime injects `ZAMP_BRANCH_ID` (with `ZAMP_DB_BRANCH_MODE` / `ZAMP_ENVIRONMENT`); the SDK sends
  them on every API-route call to that deployment as `X-BRANCH-ID` / `X-DB-BRANCH-MODE` /
  `X-ENVIRONMENT`. Nothing changes outside a branch: mode and environment are only sent with a
  branch id.
  - `zamp_sdk.context.current_branch_context()` returns the branch the process runs in
    (`{"branch_id", "db_branch_mode", "environment"}`, only the keys that are set; empty
    without a branch).
  - In-process (ActionsHub) callers need nothing: their workflow's metadata context already
    carries the branch.

## 1.2.0

- **The SDK logs action calls itself.** Every action dispatched over the API or the action
  gateway now emits its own `tool_use` / `tool_result` pair, so a script no longer has to
  mirror its own calls into the live message. Locally-registered ActionsHub actions are not
  logged — an in-process call on the worker that owns the action is plumbing, not a tool call
  the user is waiting on.
  - **Off by default**, so upgrading the SDK on its own changes nothing about what a running
    script produces. The platform turns it on.
  - **`summary=` is now the block's display title.** The one place to put a human-readable
    "what this call is doing"; without it the platform falls back to the action's configured
    display name.
  - `execute(..., log_action=True/False)` overrides the decision for one call.
  - **A script that also logs its own action calls will show two blocks for one call.** That is
    the old "mirror every action call" guidance, which is being removed: the SDK does it now, so
    delete the hand-written `emit_tool_use` / `emit_tool_result` pairs around action calls and
    keep `emit_*` for progress the action names do not convey.

- **`LoggingConfig` — one object that says how a run logs, carried with the run.** It holds the
  level, whether the script's own lines are shown at all, and whether the SDK logs action calls.
  A host binds it with `bind_logging_config()`; the code executor does so from its workflow
  input, so pantheon, the executor and the authored code all agree without anyone reading
  ambient state.
  - That matters inside a workflow: an emit there is a recorded command, so a setting read from
    the environment could differ between the first execution and a replay and fail the run.
    Config on the input is recorded in history.
  - Optional everywhere. A run that started before the field existed replays without one and
    gets the defaults.
  - A plain process that was never given one — a sandbox script — assembles the same model
    from `ZAMP_LOG_LEVEL`, `ZAMP_LOG_ENABLED` and `ZAMP_AUTO_ACTION_LOGS`, in the same style
    the channel context already travels in. Each is read on its own, so an unset or malformed
    one costs that field's default and nothing else.

- **Log levels.** `emit_info`, `emit_debug` and `emit_error` alongside the existing `emit_text`,
  gated by `configure_logging(level=..., enabled=...)`. Default `INFO`, so `emit_debug` is the
  line you can leave in the code permanently and only see when you go looking.
  - `emit_text` is unchanged — an `INFO` line, exactly as before.
  - This gate governs **only** your own emits. Silencing them leaves the SDK's action logs
    running; `configure_auto_action_logs(False)` turns those off and leaves yours working.

- **Emitted blocks are no longer mirrored into the step buffer.** The buffer holds one entry per
  action call and nothing else; the blocks were always visible in the live message, and the copy
  only restated the action entries around it.

- **Failed action calls are captured.** A step entry now carries `error` instead of `output`
  when the call raised. Previously a failure was recorded nowhere — omitting exactly the call
  that a reader of a failed run is looking for.

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
