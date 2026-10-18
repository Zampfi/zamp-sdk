# Zamp SDK

[![PyPI version](https://img.shields.io/pypi/v/zamp-sdk.svg)](https://pypi.org/project/zamp-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/zamp-sdk.svg)](https://pypi.org/project/zamp-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The official Python SDK for executing actions on the [Zamp](https://zamp.ai) platform.

## Installation

```bash
pip install zamp-sdk
```

Or with [Poetry](https://python-poetry.org/):

```bash
poetry add zamp-sdk
```

## Quick Start

```python
import asyncio
from zamp_sdk import ActionExecutor

async def main():
    result = await ActionExecutor.execute(
        "send_invoice",
        {"invoice_id": "inv_123"},
        base_url="https://api.zamp.ai",
        auth_token="your-api-token",
    )
    print(result)

asyncio.run(main())
```

### Using environment variables

Set `ZAMP_BASE_URL` and `ZAMP_AUTH_TOKEN` in your environment, then call without explicit config:

```python
result = await ActionExecutor.execute("send_invoice", {"invoice_id": "inv_123"})
```

## API Reference

### `ActionExecutor.execute()`

```python
@staticmethod
async def execute(
    action_name: str,
    params: Any,
    *,
    base_url: str | None = None,
    auth_token: str | None = None,
    summary: str | None = None,
    return_type: type | None = None,
    execution_mode: ExecutionMode | None = None,
    action_retry_policy: RetryPolicy | None = None,
    action_start_to_close_timeout: timedelta | None = None,
) -> Any
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action_name` | `str` | Yes | Name of the registered action to execute |
| `params` | `Any` | Yes | Input parameters for the action |
| `base_url` | `str \| None` | No | Zamp API base URL. Falls back to `ZAMP_BASE_URL` env var |
| `auth_token` | `str \| None` | No | API authentication token. Falls back to `ZAMP_AUTH_TOKEN` env var |
| `summary` | `str \| None` | No | Human-readable description of the execution |
| `return_type` | `type \| None` | No | Pydantic model to validate the result against |
| `execution_mode` | `ExecutionMode \| None` | No | `SYNC`, `ASYNC`, `DURABLE` (or omitted) run durably on Temporal (the API route POSTs then polls). `INLINE` runs in-process and returns the result in one request (the API route needs a platform-side opt-in per action, else 422). Ignored by the gateway route |
| `action_retry_policy` | `RetryPolicy \| None` | No | Retry configuration for the action |
| `action_start_to_close_timeout` | `timedelta \| None` | No | Maximum execution time for the action |

### `RetryPolicy`

```python
from zamp_sdk import RetryPolicy

policy = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    maximum_attempts=3,
    maximum_interval=timedelta(minutes=15),
    backoff_coefficient=1.5,
)

# Or use the default configuration:
policy = RetryPolicy.default()
```

When `action_retry_policy` is omitted from `ActionExecutor.execute()`, the SDK
applies `RetryPolicy.default()` automatically — actions fail fast (2 retries +
1 initial attempt) so script failures surface quickly. Pass an explicit policy
to opt into longer retries when needed.

| Field | Type | Default (via `.default()`) |
|-------|------|---------------------------|
| `initial_interval` | `timedelta` | 30 seconds |
| `maximum_attempts` | `int` | 3 |
| `maximum_interval` | `timedelta` | 15 minutes |
| `backoff_coefficient` | `float` | 1.5 |

## Configuration

| Environment Variable | Description |
|---------------------|-------------|
| `ZAMP_BASE_URL` | Base URL of the Zamp API (e.g. `https://api.zamp.ai`) |
| `ZAMP_AUTH_TOKEN` | API authentication token |

Explicit parameters passed to `ActionExecutor.execute()` take precedence over environment variables.

## Databases (`zamp_sdk.db`)

Access the organization's datasets by writing ordinary SQLAlchemy. The SDK compiles
your expression and ships it to the platform — **no DSN, no connection, no credential
ever reaches your script**.

```python
import sqlalchemy as sa
from sqlalchemy import select, insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from zamp_sdk.db import datasets

# Existing dataset: one line, and you get a real sqlalchemy.Table
invoices = await datasets.table("invoices")

# From here down it is stock SQLAlchemy
rows = await datasets.execute(
    select(invoices).where(invoices.c.status == "open").limit(50)
)

# Several statements, one transaction — all land or none do
async with datasets.transaction() as tx:
    tx.add(insert(invoices).values(vendor="Acme", amount=1200.50))
    tx.add(
        update(invoices).where(invoices.c.id == 7).values(status="closed"),
        expected_rows=1,          # 0 → someone else changed it → whole body rolls back
    )

# Large reads page with a keyset cursor
async for page in datasets.stream(select(invoices), page_size=10000):
    process(page)
```

### The six calls

| Call | Does |
|------|------|
| `datasets.table(name)` / `datasets.tables(names)` | Fetch schema, return live `sa.Table` objects. The plural form is **one** call |
| `datasets.execute(stmt, expected_rows=None)` | Run one statement, return its rows |
| `datasets.transaction()` | Buffer statements, ship one body as one transaction |
| `datasets.stream(stmt, page_size=10000, key="id")` | Page a large read with a keyset cursor |
| `datasets.create(table, if_exists="error"\|"skip")` | Create a dataset. **Returns the table to use** — see below |
| `datasets.drop(table_or_name)` | Delete a dataset and all its rows |

Renaming, altering, sharing, revoking and listing are called directly via
`ActionExecutor` (`agent_db_rename_dataset`, `agent_db_alter_dataset`,
`agent_db_share_dataset_access`, `agent_db_revoke_dataset_access`,
`agent_db_list_datasets`) — SQLAlchemy has no construct to compile from for those, so
a wrapper would add a surface without adding anything.

### Creating: use the returned table

Every dataset gets an auto-injected `id` primary key (added by the platform).
`create()` **returns the table as the platform describes it after creating**, so
`table.c.id` exists on the object you go on to use:

```python
customers = sa.Table("customers", sa.MetaData(),
                     sa.Column("name", sa.Text, nullable=False))

customers = await datasets.create(customers, if_exists="skip")   # ← reassign
await datasets.execute(select(customers.c.id, customers.c.name))
```

Declaring your own `id` is safe and wins — the injection is skipped.

### Errors

One exception type, `AgentDbError`, carrying Postgres's own vocabulary:

```python
from zamp_sdk import AgentDbError

try:
    await datasets.execute(stmt)
except AgentDbError as e:
    print(e.sqlstate)          # "23505" — None if it never reached Postgres
    print(e.statement_index)   # which statement in the body failed
```

`sqlstate is None` is meaningful: it says the failure happened before Postgres saw
the statement (a gate rejection, an authorization refusal). A `TimeoutError`
propagates unwrapped, because the statement may have committed.

### Writes that may run twice

A script can be re-run, so say in the SQL when a write must be safe to repeat:
`on_conflict_do_update` is idempotent by construction, and a guarded
`update(...).where(status == "pending")` is safe to repeat. Both need a unique
constraint, which you declare in the `CREATE TABLE` or add later with
`CREATE UNIQUE INDEX`.

## Evals (`zamp_sdk.evals`)

Mark the calls a script makes to the outside world, and the steps of its own logic, so an eval
trial can replay the outside world from fixtures and grade what the script did. Outside a trial
the decorators do nothing.

```python
import httpx
from zamp_sdk import evals

@evals.external_call("erp.order", key_argument="order_id")
async def fetch_order(order_id: str) -> Order:
    ...                                   # in a trial: answered from the fixture, never run

@evals.external_call("erp.page")
async def get_page(url: str) -> httpx.Response:
    ...                                   # a fixture's status/body/content/headers become a Response

@evals.observe("steps.review")
async def review(order_id: str) -> Decision:
    order = await fetch_order(order_id)   # traced with "steps.review" as its parent
    ...

entries = await evals.read_trace()        # the trial's calls so far; [] outside a trial
```

| Name | Does |
|------|------|
| `external_call(name, key_argument=None)` | In a trial, answer the call from its fixture instead of running it |
| `observe(name, key_argument=None)` | In a trial, run the function and record what it returned or raised |
| `read_trace()` | The calls this trial has traced so far, in order, as `TraceEntry` values |
| `FixtureLookupError` | Raised when the trial has no fixture left for a call; the message says which and why |

- **`key_argument`** names the parameter whose value tells calls of the same name apart (one
  fixture per order id, say). It must be a parameter of the function, or a keyword the function
  takes through `**kwargs`; a call that leaves it out, or passes `None`, has the key `None`.
- **Arguments are recorded by name**, except credential-like ones (`token`, `headers`,
  `api_key`, `*_secret`, ...), which are never written.
- **Bytes are base64.** A `bytes` value is written to the trace as base64 text, and a fixture
  value for a `bytes` return type must be base64 too.
- **Sync functions** work in a sandbox. In workflow code on ActionsHub, make a decorated function
  `async`: a sync one is refused inside a trial. Generator functions cannot be decorated.

## Error Handling

| Exception | When |
|-----------|------|
| `HttpClientError` | HTTP request fails (non-2xx status, network error, timeout). On a 4xx or 5xx, `status_code` is the response's status and the text reads `HTTP <status> from <url>`, followed by `: <message>` when the platform's error body carries one |
| `RuntimeError` | Action reaches a terminal failure state (FAILED, CANCELED, TERMINATED, TIMED_OUT) |
| `TimeoutError` | Polling for action result exceeds the timeout limit |
| `KeyError` | Required environment variable is missing and no explicit value was provided |

```python
from zamp_sdk.action_executor.utils import HttpClientError

try:
    result = await ActionExecutor.execute("my_action", params)
except HttpClientError as e:
    print(f"HTTP error {e.status_code}: {e.message}")
except RuntimeError as e:
    print(f"Action failed: {e}")
except TimeoutError as e:
    print(f"Timed out: {e}")
```

### Rate limits

The platform limits how fast an organization (and, where a rule says so, one user or agent) can
start each kind of work. A refused call was **not started**.

- `POST /actions` answered 429 raises `HttpClientError` with `status_code` 429 at once; the SDK
  retries only a 5xx, never a 429. Recognise it by `status_code == 429`, then stop, or try again
  after the wait it names, never in a loop.
- When the platform refused the call, the text reads `HTTP 429 from <url>: <message>`. The message
  says who is over which limit and how long to wait, or that the call can never fit the limit and
  must not be retried. `response_body` holds the platform's JSON, whose
  `details.retry_after_seconds` is that wait as a number (`null` when it can never fit).
- A refusal the platform reports in-band is returned as a result: a refused agent task completes
  with an `error` that starts `RATE_LIMITED:`, for the caller to read.
- A database call over the API refused for a rate limit raises `AgentDbError` from the
  `HttpClientError` (its `__cause__`).

## Development

```bash
# Clone and install
git clone https://github.com/Zampfi/zamp-sdk.git
cd zamp-sdk
make install

# Run all checks (lint + type-check + tests)
make check

# Individual targets
make lint          # ruff check + format check
make lint-fix      # auto-fix lint issues
make format        # format code
make type-check    # mypy
make test          # pytest with coverage
make clean         # remove build artifacts
```

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Run `make check` to verify lint, type-check, and tests pass
4. Open a pull request

Pre-commit hooks are configured -- install them with:

```bash
poetry run pre-commit install
```

## License

[MIT](LICENSE)
