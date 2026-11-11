"""The single place the bridge talks to the platform.

Every call funnels through here so two rules hold everywhere rather than being
re-decided per call site:

1. **Failures become AgentDbError.** Callers catch one type — whether the action
   raised, came back in the gateway's ``{"id", "status", "result", "error"}`` envelope
   with a failed status, or completed reporting ``success: false`` in its result, which
   is how ``agent_db_execute_sql`` returns a failed body. Callers get the answer from
   inside the envelope, never the envelope itself.
2. **No retry or timeout overrides are ever sent.** The platform's defaults exist
   because someone reasoned about the seam; a client-side override would silently
   replace that reasoning. Notably, write paths must not gain a retry the raw
   psycopg2 path never had.

``execution_mode`` is the one knob passed through; a caller's explicit choice always wins. When
omitted on the ``API`` host it defaults to ``DEFAULT_EXECUTION_MODE`` (INLINE); on any other host
none is sent, as before.
"""

from __future__ import annotations

from typing import Any

from zamp_sdk.action_executor import ActionExecutor, ExecutionMode
from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, SUCCESS_STATUSES
from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.db import constants
from zamp_sdk.db.utils.errors import AgentDbError


def _resolve_execution_mode(execution_mode: ExecutionMode | None) -> ExecutionMode | None:
    """The caller's mode, else INLINE on the API host; else None (the host's own default)."""
    if execution_mode is not None:
        return execution_mode
    if current_execution_host() is ExecutionHost.API:
        return constants.DEFAULT_EXECUTION_MODE
    return None


async def call(
    action_name: str,
    params: dict[str, Any],
    *,
    execution_mode: ExecutionMode | None = None,
) -> Any:
    """Execute a platform action, translating any failure to AgentDbError."""
    try:
        response = await ActionExecutor.execute(
            action_name,
            params,
            execution_mode=_resolve_execution_mode(execution_mode),
        )
    except AgentDbError:
        raise
    except TimeoutError:
        raise
    except Exception as exc:
        raise AgentDbError.from_exception(exc) from exc
    if isinstance(response, dict) and ACTION_ENVELOPE_KEYS.issubset(response):
        if response["status"] not in SUCCESS_STATUSES:
            error = response.get("error") or "unknown error"
            raise AgentDbError.from_exception(RuntimeError(f"Action {response['id']} {response['status']}: {error}"))
        response = response["result"]
    if isinstance(response, dict) and response.get("success") is False:
        raise AgentDbError.from_exception(RuntimeError(response.get("error") or f"{action_name} failed"))
    return response
