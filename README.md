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

Every dataset gets an auto-injected `id` primary key. `create()` mirrors that rule
locally and **returns the mirrored table**, so `table.c.id` exists on the object you
go on to use:

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

### Idempotency

The SDK sends no idempotency key — v1 does not honour one. When a write must be safe
to repeat, say so in the SQL: `on_conflict_do_update` is idempotent by construction,
and a guarded `update(...).where(status == "pending")` is safe to repeat. Both need a
unique constraint, which you declare in the `CREATE TABLE` or add later with
`CREATE UNIQUE INDEX`.

## Error Handling

| Exception | When |
|-----------|------|
| `HttpClientError` | HTTP request fails (non-2xx status, network error, timeout) |
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
