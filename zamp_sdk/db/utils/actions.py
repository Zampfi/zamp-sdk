"""The single place the bridge talks to the platform.

Every call funnels through here so two rules hold everywhere rather than being
re-decided per call site:

1. **Failures become AgentDbError.** Callers catch one type.
2. **No retry or timeout overrides are ever sent.** The platform's defaults exist
   because someone reasoned about the seam; a client-side override would silently
   replace that reasoning. Notably, write paths must not gain a retry the raw
   psycopg2 path never had.

``execution_mode`` is a different axis from rule 2. It selects the transport — run
the action inside the request, or on Temporal and poll — and the platform applies
its own bounds to whichever it is, so none of its reasoning is overridden. The
short, time-sensitive calls pass ``ExecutionMode.INLINE``; the rest stay on the
default.
"""

from __future__ import annotations

from typing import Any

from zamp_sdk.action_executor import ActionExecutor, ExecutionMode
from zamp_sdk.db.utils.errors import AgentDbError


async def call(
    action_name: str,
    params: dict[str, Any],
    *,
    execution_mode: ExecutionMode | None = None,
) -> Any:
    """Execute a platform action, translating any failure to AgentDbError."""
    try:
        return await ActionExecutor.execute(action_name, params, execution_mode=execution_mode)
    except AgentDbError:
        raise
    except TimeoutError:
        raise
    except Exception as exc:
        raise AgentDbError.from_exception(exc) from exc
