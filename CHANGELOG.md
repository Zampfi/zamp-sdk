# Changelog

## 0.0.14

- Raise the default client poll ceiling from 600s to 3600s (1 hour), so actions with no explicit `action_start_to_close_timeout` are polled for up to an hour before timing out

## 0.0.13

- Retry the action-create `POST /actions` on transient 5xx with exponential backoff, bounded by a time budget (the same approach as the poll loop)
- Keep polling `GET /actions/{id}` through transient 5xx responses instead of failing the action, bounded by the overall poll timeout

## 0.0.12

- Poll for the full `action_start_to_close_timeout` instead of a fixed 600s, so long-running actions are no longer abandoned client-side

## 0.0.1

- Initial release
- `ActionExecutor.execute()` for running actions via the Zamp HTTP API
- `RetryPolicy` model for configuring action retry behaviour
- Exponential-backoff polling for action results
- Support for explicit `base_url`/`auth_token` or `ZAMP_BASE_URL`/`ZAMP_AUTH_TOKEN` env vars
