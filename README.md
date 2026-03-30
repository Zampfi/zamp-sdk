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
    maximum_attempts=11,
    maximum_interval=timedelta(minutes=15),
    backoff_coefficient=1.5,
)

# Or use the default configuration:
policy = RetryPolicy.default()
```

| Field | Type | Default (via `.default()`) |
|-------|------|---------------------------|
| `initial_interval` | `timedelta` | 30 seconds |
| `maximum_attempts` | `int` | 11 |
| `maximum_interval` | `timedelta` | 15 minutes |
| `backoff_coefficient` | `float` | 1.5 |

## Configuration

| Environment Variable | Description |
|---------------------|-------------|
| `ZAMP_BASE_URL` | Base URL of the Zamp API (e.g. `https://api.zamp.ai`) |
| `ZAMP_AUTH_TOKEN` | API authentication token |

Explicit parameters passed to `ActionExecutor.execute()` take precedence over environment variables.

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
