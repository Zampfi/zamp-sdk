"""The single place the bridge talks to the platform.

Every call funnels through here so two rules hold everywhere rather than being
re-decided per call site:

1. **Failures become AgentDbError.** Callers catch one type — whether the action
   failed outright or completed reporting ``success: false`` in its result, which is
   how ``agent_db_execute_sql`` returns a failed body.
2. **No retry or timeout overrides are ever sent.** The platform's defaults exist
   because someone reasoned about the seam; a client-side override would silently
   replace that reasoning. Notably, write paths must not gain a retry the raw
   psycopg2 path never had.
"""

from __future__ import annotations

from typing import Any

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.db.utils.errors import AgentDbError


async def call(action_name: str, params: dict[str, Any]) -> Any:
    """Execute a platform action, translating any failure to AgentDbError."""
    try:
        response = await ActionExecutor.execute(action_name, params)
    except AgentDbError:
        raise
    except TimeoutError:
        raise
    except Exception as exc:
        raise AgentDbError.from_exception(exc) from exc
    return _answer(action_name, response)


def _answer(action_name: str, response: Any) -> Any:
    """The action's own result, raising for a failure however the route reported it.

    The API route has already unwrapped a completed action and raised for a failed one.
    The gateway route hands back its ``{"id", "status", "result", "error"}`` envelope
    untouched, with a failure reported as a value. And ``agent_db_execute_sql`` reports a
    failed body as a completed action whose result is ``{"success": false, "error": ...}``.
    """
    if isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response):
        status = response["status"]
        if status not in SUCCESS_STATUSES:
            error = response.get("error") or "unknown error"
            raise AgentDbError.from_exception(RuntimeError(f"Action {response['id']} {status}: {error}"))
        response = response["result"]
    if isinstance(response, dict) and response.get("success") is False:
        raise AgentDbError.from_exception(RuntimeError(response.get("error") or f"{action_name} failed"))
    return response
