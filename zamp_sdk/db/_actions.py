"""The single place the bridge talks to the platform.

Every call funnels through here so two rules hold everywhere rather than being
re-decided per call site:

1. **Failures become AgentDbError.** Callers catch one type.
2. **No retry or timeout overrides are ever sent.** The platform's defaults exist
   because someone reasoned about the seam; a client-side override would silently
   replace that reasoning. Notably, write paths must not gain a retry the raw
   psycopg2 path never had.
"""

from __future__ import annotations

from typing import Any

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.db.errors import AgentDbError


async def call(
    action_name: str,
    params: dict[str, Any],
    *,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> Any:
    """Execute a platform action, translating any failure to AgentDbError."""
    try:
        return await ActionExecutor.execute(
            action_name,
            params,
            base_url=base_url,
            auth_token=auth_token,
        )
    except AgentDbError:
        raise
    except TimeoutError:
        raise
    except Exception as exc:
        raise AgentDbError.from_exception(exc) from exc
